import { env } from '$env/dynamic/private';

// URL de la API (FastAPI). Solo el servidor de SvelteKit la usa: el navegador nunca llama a la API directo.
export const BACKEND_URL = (env.BACKEND_URL || 'http://localhost:8000').replace(/\/+$/, '');
