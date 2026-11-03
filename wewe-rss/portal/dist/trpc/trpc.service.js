"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __metadata = (this && this.__metadata) || function (k, v) {
    if (typeof Reflect === "object" && typeof Reflect.metadata === "function") return Reflect.metadata(k, v);
};
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.TrpcService = void 0;
const common_1 = require("@nestjs/common");
const config_1 = require("@nestjs/config");
const constants_1 = require("../constants");
const prisma_service_1 = require("../prisma/prisma.service");
const server_1 = require("@trpc/server");
const axios_1 = __importDefault(require("axios"));
const dayjs_1 = __importDefault(require("dayjs"));
const timezone_1 = __importDefault(require("dayjs/plugin/timezone"));
const utc_1 = __importDefault(require("dayjs/plugin/utc"));
dayjs_1.default.extend(utc_1.default);
dayjs_1.default.extend(timezone_1.default);
const blockedAccountsMap = new Map();
let TrpcService = class TrpcService {
    constructor(prismaService, configService) {
        this.prismaService = prismaService;
        this.configService = configService;
        this.trpc = server_1.initTRPC.create();
        this.publicProcedure = this.trpc.procedure;
        this.protectedProcedure = this.trpc.procedure.use(({ ctx, next }) => {
            const errorMsg = ctx.errorMsg;
            if (errorMsg) {
                throw new server_1.TRPCError({ code: 'UNAUTHORIZED', message: errorMsg });
            }
            return next({ ctx }).then((result) => {
                    if (process.env.SCHOOLSEARCH_PUBLIC_WORKSPACE !== '1') return result;
                    if (result.ok) return { ...result, data: require('../portal-public.cjs').redact(result.data) };
                    if (result.error?.code === 'INTERNAL_SERVER_ERROR') {
                        return { ...result, error: new server_1.TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: '处理失败，请稍后重试' }) };
                    }
                    return result;
                });
        });
        this.router = this.trpc.router;
        this.mergeRouters = this.trpc.mergeRouters;
        this.updateDelayTime = 60;
        this.logger = new common_1.Logger(this.constructor.name);
        this.removeBlockedAccount = (vid) => {
            const today = this.getTodayDate();
            const blockedAccounts = blockedAccountsMap.get(today);
            if (Array.isArray(blockedAccounts)) {
                const newBlockedAccounts = blockedAccounts.filter((id) => id !== vid);
                blockedAccountsMap.set(today, newBlockedAccounts);
            }
        };
        this.inProgressHistoryMp = {
            id: '',
            page: 1,
        };
        this.isRefreshAllMpArticlesRunning = false;
        const { url } = this.configService.get('platform');
        this.updateDelayTime =
            this.configService.get('feed').updateDelayTime;
        this.request = axios_1.default.create({ baseURL: url, timeout: 15 * 1e3 });
        this.request.interceptors.response.use((response) => {
            return response;
        }, async (error) => {
            this.logger.log('error: ', error);
            const errMsg = error.response?.data?.message || '';
            const id = error.config.headers.xid;
            if (errMsg.includes('WeReadError401')) {
                await this.prismaService.account.update({
                    where: { id },
                    data: { status: constants_1.statusMap.INVALID },
                });
                this.logger.error(`账号（${id}）登录失效，已禁用`);
            }
            else if (errMsg.includes('WeReadError429')) {
                this.logger.error(`账号（${id}）请求频繁，打入小黑屋`);
            }
            const today = this.getTodayDate();
            const blockedAccounts = blockedAccountsMap.get(today);
            if (Array.isArray(blockedAccounts)) {
                if (id) {
                    blockedAccounts.push(id);
                }
                blockedAccountsMap.set(today, blockedAccounts);
            }
            else if (errMsg.includes('WeReadError400')) {
                this.logger.error(`账号（${id}）处理请求参数出错`);
                this.logger.error('WeReadError400: ', errMsg);
                await new Promise((resolve) => setTimeout(resolve, 10 * 1e3));
            }
            else {
                this.logger.error("Can't handle this error: ", errMsg);
            }
            return Promise.reject(error);
        });
    }
    getTodayDate() {
        return dayjs_1.default.tz(new Date(), 'Asia/Shanghai').format('YYYY-MM-DD');
    }
    getBlockedAccountIds() {
        const today = this.getTodayDate();
        const disabledAccounts = blockedAccountsMap.get(today) || [];
        this.logger.debug('disabledAccounts: ', disabledAccounts);
        return disabledAccounts.filter(Boolean);
    }
    async getAvailableAccount() {
        const disabledAccounts = this.getBlockedAccountIds();
        const account = await this.prismaService.account.findMany({
            where: {
                status: constants_1.statusMap.ENABLE,
                NOT: {
                    id: { in: disabledAccounts },
                },
            },
            take: 10,
        });
        if (!account || account.length === 0) {
            throw new Error('暂无可用读书账号!');
        }
        return account[Math.floor(Math.random() * account.length)];
    }
    async getMpArticles(mpId, page = 1, retryCount = 3) {
        const account = await this.getAvailableAccount();
        try {
            const res = await this.request
                .get(`/api/v2/platform/mps/${mpId}/articles`, {
                headers: {
                    xid: account.id,
                    Authorization: `Bearer ${account.token}`,
                },
                params: {
                    page,
                },
            })
                .then((res) => res.data)
                .then((res) => {
                this.logger.log(`getMpArticles(${mpId}) page: ${page} articles: ${res.length}`);
                return res;
            });
            return res;
        }
        catch (err) {
            this.logger.error(`retry(${4 - retryCount}) getMpArticles  error: `, err);
            if (retryCount > 0) {
                return this.getMpArticles(mpId, page, retryCount - 1);
            }
            else {
                throw err;
            }
        }
    }
    async refreshMpArticlesAndUpdateFeed(mpId, page = 1) {
        const articles = await this.getMpArticles(mpId, page);
        if (articles.length > 0) {
            let results;
            const { type } = this.configService.get('database');
            if (type === 'sqlite') {
                const inserts = articles.map(({ id, picUrl, publishTime, title }) => this.prismaService.article.upsert({
                    create: { id, mpId, picUrl, publishTime, title },
                    update: {
                        publishTime,
                        title,
                    },
                    where: { id },
                }));
                results = await this.prismaService.$transaction(inserts);
            }
            else {
                results = await this.prismaService.article.createMany({
                    data: articles.map(({ id, picUrl, publishTime, title }) => ({
                        id,
                        mpId,
                        picUrl,
                        publishTime,
                        title,
                    })),
                    skipDuplicates: true,
                });
            }
            this.logger.debug(`refreshMpArticlesAndUpdateFeed create results: ${JSON.stringify(results)}`);
        }
        const hasHistory = articles.length < constants_1.defaultCount ? 0 : 1;
        await this.prismaService.feed.update({
            where: { id: mpId },
            data: {
                syncTime: Math.floor(Date.now() / 1e3),
                hasHistory,
            },
        });
        return { hasHistory };
    }
    async getHistoryMpArticles(mpId) {
        if (this.inProgressHistoryMp.id === mpId) {
            this.logger.log(`getHistoryMpArticles(${mpId}) is running`);
            return;
        }
        this.inProgressHistoryMp = {
            id: mpId,
            page: 1,
        };
        if (!this.inProgressHistoryMp.id) {
            return;
        }
        try {
            const feed = await this.prismaService.feed.findFirstOrThrow({
                where: {
                    id: mpId,
                },
            });
            if (feed.hasHistory === 0) {
                this.logger.log(`getHistoryMpArticles(${mpId}) has no history`);
                return;
            }
            const total = await this.prismaService.article.count({
                where: {
                    mpId,
                },
            });
            this.inProgressHistoryMp.page = Math.ceil(total / constants_1.defaultCount);
            let i = 1e3;
            while (i-- > 0) {
                if (this.inProgressHistoryMp.id !== mpId) {
                    this.logger.log(`getHistoryMpArticles(${mpId}) is not running, break`);
                    break;
                }
                const { hasHistory } = await this.refreshMpArticlesAndUpdateFeed(mpId, this.inProgressHistoryMp.page);
                if (hasHistory < 1) {
                    this.logger.log(`getHistoryMpArticles(${mpId}) has no history, break`);
                    break;
                }
                this.inProgressHistoryMp.page++;
                await new Promise((resolve) => setTimeout(resolve, this.updateDelayTime * 1e3));
            }
        }
        finally {
            this.inProgressHistoryMp = {
                id: '',
                page: 1,
            };
        }
    }
    async refreshAllMpArticlesAndUpdateFeed() {
        if (this.isRefreshAllMpArticlesRunning) {
            this.logger.log('refreshAllMpArticlesAndUpdateFeed is running');
            return;
        }
        const mps = await this.prismaService.feed.findMany();
        this.isRefreshAllMpArticlesRunning = true;
        try {
            for (const { id } of mps) {
                await this.refreshMpArticlesAndUpdateFeed(id);
                await new Promise((resolve) => setTimeout(resolve, this.updateDelayTime * 1e3));
            }
        }
        finally {
            this.isRefreshAllMpArticlesRunning = false;
        }
    }
    async getMpInfo(url) {
        url = url.trim();
        const account = await this.getAvailableAccount();
        return this.request
            .post(`/api/v2/platform/wxs2mp`, { url }, {
            headers: {
                xid: account.id,
                Authorization: `Bearer ${account.token}`,
            },
        })
            .then((res) => res.data);
    }
    async createLoginUrl() {
        return this.request
            .get(`/api/v2/login/platform`)
            .then((res) => res.data);
    }
    async getLoginResult(id) {
        return this.request
            .get(`/api/v2/login/platform/${id}`, { timeout: 120 * 1e3 })
            .then((res) => res.data);
    }
};
exports.TrpcService = TrpcService;
exports.TrpcService = TrpcService = __decorate([
    (0, common_1.Injectable)(),
    __metadata("design:paramtypes", [prisma_service_1.PrismaService,
        config_1.ConfigService])
], TrpcService);
//# sourceMappingURL=trpc.service.js.map