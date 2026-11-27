export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: false },

  modules: [
    '@nuxt/ui',
    '@pinia/nuxt',
  ],

  css: ['~/assets/css/main.css'],

  colorMode: {
    preference: 'system',
    fallback: 'light',
    classSuffix: '',
  },

  devServer: {
    host: '127.0.0.1',
    port: 3100,
  },

  runtimeConfig: {
    apiProxyTarget: 'http://127.0.0.1:8100',
    public: {
      appName: 'ContentHub AI',
      defaultTimezone: 'Asia/Manila',
    },
  },

  app: {
    head: {
      title: 'ContentHub AI',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'robots', content: 'noindex, nofollow' },
      ],
    },
  },

  typescript: {
    strict: true,
    typeCheck: false,
  },
})
