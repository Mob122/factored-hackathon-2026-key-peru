import type { RequestHandler } from './$types';
import { BACKEND_URL } from '$lib/server/backend';

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
                return new Response(JSON.stringify(cuerpo), {
                    status: respuesta.status,
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
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
                return new Response(JSON.stringify(cuerpo), {
                    status: respuesta.status,
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
            }      
            
            if (cuerpo) {
                cookies.set('token', cuerpo as string, {
                    path: '/', // La cookie estará disponible en todas las rutas.
                    httpOnly: true, // Invisible para JavaScript del lado del cliente.
                    secure: true, // Incluye la cookie solo en solicitudes HTTPS.
                    sameSite: 'strict', // Previene el envío de la cookie en solicitudes de sitios cruzados.
                    maxAge: 60 * 60 * 24 * 7 // La cookie expira en 7 días.
                })
            }
        }
        
        

        return new Response(JSON.stringify(cuerpo), {
            status: 200,
            headers: {
                'Content-Type': 'application/json'
            }
        });
    } catch (error) {
        return new Response(JSON.stringify({ error: 'Error en el servidor' }), {
            status: 500,
            headers: {
                'Content-Type': 'application/json'
            }
        });
    }    
};