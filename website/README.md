# Sito web

Landing statica in Astro. SEO: meta Open Graph, JSON-LD, sitemap, `robots.txt` dinamico.

```bash
npm install
npm run dev
npm run build
```

Deploy su Vercel: crea il progetto con **Root Directory** = `website` (Import GitHub). Config in `website/vercel.json`.

```bash
cd website
npx vercel link
npx vercel --prod
```

Variabile opzionale `SITE_URL` (es. dominio produzione) sovrascrive l’URL canonico in build.
