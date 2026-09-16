# Buno Web

Frontend React + TypeScript + Vite. Instruções completas em `../README.md`.

```sh
npm ci
npm run dev
```

O Vite encaminha `/api` para `http://127.0.0.1:8000`. O endereço pode ser trocado
com `API_PROXY_TARGET`. Para produção em origens diferentes, use `VITE_API_URL`
antes do build e configure as origens permitidas na API.

`npm test` verifica a leitura de streaming; `npm run build` compila para `dist/`.
`npm run lint` verifica o código. Use Node.js 24.
