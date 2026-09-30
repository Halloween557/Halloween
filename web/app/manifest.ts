import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'G.I.D.E.O.N. PC Agent',
    short_name: 'GIDEON',
    description: 'Autonomous Windows PC Control & Intelligence Platform',
    start_url: '/',
    display: 'standalone',
    background_color: '#080c14',
    theme_color: '#080c14',
    orientation: 'portrait',
    icons: [
      {
        src: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%236366f1'><path d='M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5zm8 14a1 1 0 0 1 1-1h3a1 1 0 1 1 0 2h-3a1 1 0 0 1-1-1zm-6 0a1 1 0 1 1 0-2h3a1 1 0 0 1 0 2H6z'/></svg>",
        sizes: '192x192 512x512',
        type: 'image/svg+xml',
        purpose: 'any',
      },
    ],
  };
}
