// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

const site =
  process.env.SITE_URL?.replace(/\/$/, '') ||
  'https://battaglia-navale.vercel.app';

/** @type {import('astro').AstroUserConfig} */
export default defineConfig({
  site,
  trailingSlash: 'never',
  compressHTML: true,
  integrations: [sitemap()],
});
