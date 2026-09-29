/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PAYMENT_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
