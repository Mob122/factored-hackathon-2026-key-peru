// Etiquetas y formatos de la UI para los valores de gold y de la API (contrato chat_api.md, secciones 4.7 y 10).

export const ESTADOS_TARJETA: Record<string, { texto: string; color: string }> = {
	Active: { texto: 'Activa', color: 'bg-green-500' },
	Blocked: { texto: 'Bloqueada', color: 'bg-red-500' },
	Suspended: { texto: 'Suspendida', color: 'bg-amber-500' },
	Closed: { texto: 'Cerrada', color: 'bg-slate-400' }
};

export const TIPOS_TRANSACCION: Record<string, string> = {
	Purchase: 'Compra',
	Withdrawal: 'Retiro',
	Payment: 'Pago'
};

// Con `!`: la regla `section p` de layout.css no está en una capa y, sin `!`, ganaría al color.
export const ESTADOS_TRANSACCION: Record<string, { texto: string; clase: string }> = {
	Approved: { texto: 'Aprobada', clase: 'text-green-700!' },
	Declined: { texto: 'Rechazada', clase: 'text-red-600!' },
	Pending: { texto: 'Pendiente', clase: 'text-amber-600!' },
	Reversed: { texto: 'Revertida', clase: 'text-slate-500!' }
};

// Intenciones de docs/intents.md que pueden terminar en un caso.
export const MOTIVOS_CASO: Record<string, string> = {
	charge_dispute: 'Reclamo de un cargo',
	human_request: 'Pedido de un asesor',
	card_block: 'Bloqueo de tarjeta',
	card_unblock: 'Desbloqueo o reposición',
	block_reason: 'Motivo de un bloqueo',
	transaction_detail: 'Consulta de una transacción',
	transaction_list: 'Consulta de movimientos',
	card_status: 'Estado de una tarjeta',
	card_list: 'Consulta de tarjetas',
	balance_inquiry: 'Consulta de saldo',
	out_of_scope: 'Otra consulta'
};

export const motivoCaso = (motivo: string | null) => (motivo ? (MOTIVOS_CASO[motivo] ?? motivo) : 'Revisión de la cuenta');

// POL-HND-15: urgent > security > normal.
export const PRIORIDADES: Record<string, { texto: string; orden: number; clase: string }> = {
	urgent: { texto: 'Urgente', orden: 0, clase: 'bg-red-50 text-red-700' },
	security: { texto: 'Seguridad', orden: 1, clase: 'bg-amber-50 text-amber-700' },
	normal: { texto: 'Normal', orden: 2, clase: 'bg-slate-100 text-slate-600' }
};

// "Tarjeta Crédito" → "crédito", para las frases que se envían al asistente.
export const tipoCorto = (tipo: string) => (tipo.includes('Débito') ? 'débito' : 'crédito');

// Montos de gold: string decimal, siempre positivo, en la moneda de la transacción. Nunca se suman monedas distintas.
export function formatearMonto(monto: string, moneda: string): string {
	const valor = Number(monto).toLocaleString('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	return `${valor} ${moneda}`;
}

// Fechas del reloj del banco: llegan sin zona ("2026-06-06T19:43:19") y se muestran tal cual, en hora del banco.
export function formatearFechaBanco(iso: string, conHora = true): string {
	const [fecha, hora = ''] = iso.split('T');
	const [anio, mes, dia] = fecha.split('-').map(Number);
	const meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
	const texto = `${dia} ${meses[mes - 1]} ${anio}`;
	return conHora && hora ? `${texto}, ${hora.slice(0, 5)}` : texto;
}

// "6 de junio de 2026", como lo escribe el cliente en el chat.
export function fechaLarga(iso: string): string {
	const [anio, mes, dia] = iso.slice(0, 10).split('-').map(Number);
	const meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
	return `${dia} de ${meses[mes - 1]} de ${anio}`;
}

// Horas reales (UTC con zona): sesiones, casos y conversaciones.
export function formatearFecha(iso: string): string {
	return new Date(iso).toLocaleString('es', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
