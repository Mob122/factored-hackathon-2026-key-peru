import type { RequestHandler } from './$types';
import { json } from '@sveltejs/kit';
import { BACKEND_URL, COOKIE_TOKEN, OPCIONES_COOKIE } from '$lib/server/backend';

export const POST: RequestHandler = async ({request, cookies, url}) => {
    try {
        const urlParams = new URLSearchParams(url.search);
        const tipoAuth = urlParams.get('tipoAuth');

        const data = await request.json();
        let cuerpo: string | Record<string, any> = '';

        if (tipoAuth === 'registrarse') {
            const { correo_electronico, password, nombre } = data;
            const respuesta = await fetch(`${BACKEND_URL}/autenticacion/registrar`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    correo_electronico,
                    password,
                    nombre
                })
            });

            cuerpo = await respuesta.json();

            if (!respuesta.ok) {
                return json(cuerpo, { status: respuesta.status });
            }

        } else if (tipoAuth === 'login') {
            const { correo_electronico, password } = data;

            const respuesta = await fetch(`${BACKEND_URL}/autenticacion/iniciar-sesion`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    correo_electronico,
                    password
                })
            });

            cuerpo = await respuesta.json();

            if (!respuesta.ok) {
                return json(cuerpo, { status: respuesta.status });
            }

            if (cuerpo) {
                // El token nunca llega al navegador: la cookie es httpOnly y vive lo que la sesión del backend (60 min).
                cookies.set(COOKIE_TOKEN, cuerpo as string, OPCIONES_COOKIE);
            }
            // El token no se devuelve al navegador.
            cuerpo = { ok: true };
        }

        return json(cuerpo, { status: 200 });
    } catch (error) {
        return json({ error: 'No se pudo conectar con el servidor del banco.' }, { status: 502 });
    }
};
