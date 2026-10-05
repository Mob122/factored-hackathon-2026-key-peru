// Pantallas de cada rol (contrato chat_api.md, sección 2): el cliente con customer_id usa el portal y el chat,
// el agente la bandeja de casos. El jurado y un usuario registrado sin cliente solo ven un aviso en /app.
type Usuario = NonNullable<App.Locals['usuario']>;

const PORTAL_CLIENTE = ['/app/consultas', '/app/tarjetas', '/app/transacciones', '/app/casos', '/app/actividad', '/app/ayuda'];

export const esCliente = (usuario: Usuario) => usuario.rol === 'cliente' && !!usuario.customer_id;

export const inicioDelRol = (usuario: Usuario) => (usuario.rol === 'agente' ? '/app/bandeja' : '/app');

const dentro = (ruta: string, base: string) => ruta === base || ruta.startsWith(base + '/');

export function rutaPermitida(usuario: Usuario, ruta: string): boolean {
	if (usuario.rol === 'agente') return dentro(ruta, '/app/bandeja');
	if (esCliente(usuario)) return ruta === '/app' || PORTAL_CLIENTE.some((base) => dentro(ruta, base));
	return ruta === '/app' || dentro(ruta, '/app/ayuda');
}
