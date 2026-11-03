"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const core_1 = require("@nestjs/core");
const app_module_1 = require("./app.module");
const trpc_router_1 = require("./trpc/trpc.router");
const config_1 = require("@nestjs/config");
const express_1 = require("express");
const path_1 = require("path");
const fs_1 = require("fs");
const packageJson = JSON.parse((0, fs_1.readFileSync)((0, path_1.resolve)(__dirname, '..', './package.json'), 'utf-8'));
const appVersion = packageJson.version;
console.log('appVersion: v' + appVersion);
async function bootstrap() {
    const app = await core_1.NestFactory.create(app_module_1.AppModule);
    const configService = app.get(config_1.ConfigService);
    const { host, isProd, port } = configService.get('server');
    app.use((0, express_1.json)({ limit: '10mb' }));
    app.use((0, express_1.urlencoded)({ extended: true, limit: '10mb' }));
    require('./portal-public.cjs').install(app);
    app.useStaticAssets((0, path_1.join)(__dirname, '..', 'client', 'assets'), {
        prefix: '/dash/assets/',
    });
    app.setBaseViewsDir((0, path_1.join)(__dirname, '..', 'client'));
    app.setViewEngine('hbs');
    if (isProd) {
        app.enable('trust proxy');
    }
    app.enableCors({
        exposedHeaders: ['authorization'],
    });
    const trpc = app.get(trpc_router_1.TrpcRouter);
    trpc.applyMiddleware(app);
    await app.listen(port, host);
    console.log(`Server is running at http://${host}:${port}`);
}
bootstrap();
//# sourceMappingURL=main.js.map