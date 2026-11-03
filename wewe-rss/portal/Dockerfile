FROM cooderl/wewe-rss-sqlite@sha256:349a1ec9478d767de72e69bf5a7cf12e6bb0df879bbd8b4522cd82819d003766
COPY client/index.hbs /app/client/index.hbs
COPY client/assets/index-DdrV8jkS.js /app/client/assets/index-DdrV8jkS.js
COPY client/assets/index-CGqyX068.css /app/client/assets/index-CGqyX068.css
COPY dist/main.js /app/dist/main.js
COPY dist/portal-public.cjs /app/dist/portal-public.cjs
COPY dist/trpc/trpc.service.js /app/dist/trpc/trpc.service.js
CMD ["node", "dist/main"]
