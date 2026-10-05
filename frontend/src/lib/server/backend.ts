import { env } from '$env/dynamic/private';

// URL de la API (FastAPI). Solo el servidor de SvelteKit la usa: el navegador nunca llama a la API directo.
// API_BCKD_8 se mantiene como alias de la configuración de producción del frontend.
export const BACKEND_URL = (env.BACKEND_URL || env.API_BCKD_8 || 'http://localhost:8000').replace(/\/+$/, '');
