// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		interface Locals {
			// GET /autenticacion/mi-perfil (contrato chat_api.md, sección 3).
			usuario: {
				id: number;
				nombre: string;
				correo_electronico: string;
				es_activo: boolean;
				rol: 'cliente' | 'agente' | 'jurado';
				customer_id: string | null;
			} | null;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
