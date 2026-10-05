// Respuestas de la API (docs/contracts/chat_api.md; openapi.json tiene el esquema completo).

// Portal del cliente (sección 4.7).
export type Tarjeta = { ref: string; last4: string; tipo: string; estado: string };

export type Transaccion = {
	fecha: string;
	tipo: string;
	monto: string;
	moneda: string;
	comercio: string | null;
	estado: string;
};

export type TransaccionesTarjeta = Tarjeta & { truncada: boolean; transacciones: Transaccion[] };

export type Transacciones = { desde: string; hasta: string; tarjetas: TransaccionesTarjeta[] };

export type CasoCliente = {
	case_id: string;
	creado_en: string;
	prioridad: string;
	motivo: string | null;
	tarjetas_last4: string[];
	mensajes_agregados: number;
	conversation_id: string;
};

export type ConversacionCliente = {
	conversation_id: string;
	estado: string;
	turnos: number;
	idioma: string | null;
	case_id: string | null;
	creada_en: string;
	actualizada_en: string;
};

// Chat (sección 4).
export type EstadoChat =
	| 'IDLE'
	| 'CLARIFY_INTENT'
	| 'SELECT_CARD'
	| 'SELECT_TRANSACTION'
	| 'OFFER_BLOCK'
	| 'STEP_UP'
	| 'AWAIT_CONFIRMATION'
	| 'HANDED_OFF'
	| 'ENDED'
	| 'SESSION_EXPIRED';

export type RespuestaChat = {
	conversation_id: string;
	reply: string;
	state: EstadoChat;
	language: 'es' | 'pt';
	pending_confirmation: { card_last4: string; card_type: string; expires_at: string } | null;
	case_id: string | null;
	turn: number;
};

export type CodigoSms = { codigo: string; expira_en: string; canal: string; aviso: string };

// Bandeja del agente (secciones 5, 10 y 11).
export type ResumenCaso = {
	case_id: string;
	created_at: string;
	priority: string;
	reason_rule_ids: string[];
	language: string;
	customer_id: string;
	auth_level: string;
};

export type LecturaCaso = ResumenCaso & {
	policy_version: string;
	conversation_ref: string;
	appended_messages: { text_redacted: string; received_at: string }[];
	request: {
		last_message_redacted?: string;
		summary?: string;
		summary_generated_by?: string;
		top_intent?: string;
		conformal_set?: string[];
	} | string;
	verified_facts: { fact: string; value: unknown; tool_call_id: string }[];
	actions_taken: Record<string, unknown>[];
	evidence: {
		tool_calls?: { tool_call_id: string; tool: string; called_at: string; status: string; result_ref: string }[];
		cards?: { card_id: string; last4: string }[];
		transactions?: string[];
		security_events?: unknown[];
	};
	unresolved_questions: string[];
};

export type EventoAuditoria = Record<string, unknown> & {
	event_type: string;
	turn_index: number;
	occurred_at: string;
	state: string;
	rule_ids: string[];
};

export type EventosConversacion = { conversation_id: string; total: number; cadena_valida: boolean; eventos: EventoAuditoria[] };
