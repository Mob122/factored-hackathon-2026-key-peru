<script lang="ts">
	import { PRIORIDADES, formatearFecha, motivoCaso } from '$lib/utils/formato';
	import type { EventoAuditoria } from '$lib/types';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    const caso = $derived(data.caso);
    const pedido = $derived(typeof caso.request === 'string' ? { summary: caso.request } : caso.request);
    const prioridad = $derived(PRIORIDADES[caso.priority] ?? { texto: caso.priority, orden: 9, clase: 'bg-slate-100 text-slate-600' });

    // El audit trail agrupado por turno: las explicaciones salen de los eventos, nunca del razonamiento de un modelo (POL-AUD-02).
    const turnos = $derived.by(() => {
        const grupos = new Map<number, EventoAuditoria[]>();
        for (const evento of data.auditoria?.eventos ?? []) {
            grupos.set(evento.turn_index, [...(grupos.get(evento.turn_index) ?? []), evento]);
        }
        return [...grupos.entries()].sort(([a], [b]) => a - b);
    });

    const valor = (dato: unknown): string =>
        dato !== null && typeof dato === 'object'
            ? Object.entries(dato as Record<string, unknown>).map(([clave, v]) => `${clave}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')
            : String(dato);

    const campo = (evento: EventoAuditoria, nombre: string) => evento[nombre] as any;

    // Una línea por evento, con los campos de audit_log.md sección 4 que explican el turno.
    function resumen(evento: EventoAuditoria): string {
        switch (evento.event_type) {
            case 'message_received': return `Cliente: «${campo(evento, 'text_redacted')}»`;
            case 'classification': return `Clasificación: ${campo(evento, 'top_intent')} (conjunto ${JSON.stringify(campo(evento, 'conformal_set'))}, ruta ${campo(evento, 'routing')})`;
            case 'tool_call': return `Tool ${campo(evento, 'tool_call_id')}: ${campo(evento, 'tool')} → ${campo(evento, 'status')}`;
            case 'policy_decision': return `Decisión: ${campo(evento, 'decision')} · ${campo(evento, 'state_before')} → ${campo(evento, 'state_after')} (${(campo(evento, 'transitions') ?? []).join(', ')})`;
            case 'session': return `Sesión: ${campo(evento, 'session_event')} (${campo(evento, 'auth_level_before')} → ${campo(evento, 'auth_level_after')})`;
            case 'handoff': return `Transferencia: ${campo(evento, 'handoff_event')} ${campo(evento, 'case_id') ?? ''} · prioridad ${campo(evento, 'priority')}`;
            case 'confirmation': return `Confirmación ${campo(evento, 'confirmation_event')}: ${campo(evento, 'outcome') ?? 'pendiente'} · •••• ${campo(evento, 'last4')}`;
            case 'action_result': return `Acción ${campo(evento, 'action')} •••• ${campo(evento, 'last4')}: ejecutada ${campo(evento, 'executed')}`;
            case 'verification': return `Verificación: esperado ${campo(evento, 'expected_status')}, leído ${campo(evento, 'observed_status')} (verificada ${campo(evento, 'verified')})`;
            case 'security': return `Seguridad: ${campo(evento, 'security_event')}${campo(evento, 'subtype') ? ` (${campo(evento, 'subtype')})` : ''}`;
            case 'llm_call': return `LLM: ${campo(evento, 'status')}`;
            default: return evento.event_type;
        }
    }
</script>

<svelte:head>
    <title>{caso.case_id} | Bandeja</title>
</svelte:head>

<div class="space-y-4">
    <section>
        <div class="space-y-3">
            <a href="/app/bandeja" class="inline-block px-0! py-0! text-sm hover:bg-transparent! hover:text-red-600!">← Bandeja de casos</a>
            <div class="flex flex-wrap gap-2 items-center">
                <h1 class="font-mono">{caso.case_id}</h1>
                <span class={`font-semibold px-2 py-1 rounded-md text-xs ${prioridad.clase}`}>{prioridad.texto}</span>
            </div>
            <p>
                {motivoCaso(pedido.top_intent ?? null)} · {formatearFecha(caso.created_at)} · cliente <span class="font-mono">{caso.customer_id}</span> ·
                {caso.language === 'pt' ? 'portugués' : 'español'} · {caso.auth_level} · {caso.policy_version}
            </p>
        </div>
    </section>

    <section>
        <div class="grid gap-4 xl:grid-cols-2">
            <div class="bg-white p-4 rounded-2xl space-y-3">
                <h3 class="font-bold text-lg!">Pedido</h3>
                {#if pedido.last_message_redacted}
                    <p class="bg-slate-50 p-3 rounded-xl text-sm!">«{pedido.last_message_redacted}»</p>
                {/if}
                {#if pedido.summary}
                    <p class="text-sm!">{pedido.summary} <span class="text-slate-400">({pedido.summary_generated_by ?? 'template'})</span></p>
                {/if}
                {#if pedido.conformal_set}
                    <p class="text-sm!">Conjunto conforme: <span class="font-mono">{pedido.conformal_set.join(', ')}</span></p>
                {/if}
                <p class="text-sm!">Reglas: {#each caso.reason_rule_ids as regla}<span class="bg-slate-100 font-mono mr-1 px-2 py-0.5 rounded-md text-xs">{regla}</span>{/each}</p>
            </div>

            <div class="bg-white p-4 rounded-2xl space-y-3">
                <h3 class="font-bold text-lg!">Preguntas abiertas</h3>
                <ul class="list-disc list-inside space-y-1 text-sm">
                    {#each caso.unresolved_questions as pregunta}
                        <li>{pregunta}</li>
                    {/each}
                </ul>
            </div>

            <div class="bg-white p-4 rounded-2xl space-y-3">
                <h3 class="font-bold text-lg!">Hechos verificados</h3>
                {#if caso.verified_facts.length}
                    <ul class="space-y-2 text-sm">
                        {#each caso.verified_facts as hecho}
                            <li class="bg-slate-50 p-2 rounded-lg">
                                <span class="font-semibold">{hecho.fact}</span>
                                <span class="font-mono text-slate-400 text-xs">({hecho.tool_call_id})</span>
                                <span class="block break-words font-mono text-xs">{valor(hecho.value)}</span>
                            </li>
                        {/each}
                    </ul>
                {:else}
                    <p class="text-sm!">Ninguno.</p>
                {/if}
            </div>

            <div class="bg-white p-4 rounded-2xl space-y-3">
                <h3 class="font-bold text-lg!">Acciones y mensajes</h3>
                {#if caso.actions_taken.length}
                    <ul class="space-y-2 text-sm">
                        {#each caso.actions_taken as accion}
                            <li class="bg-slate-50 break-words font-mono p-2 rounded-lg text-xs">{valor(accion)}</li>
                        {/each}
                    </ul>
                {:else}
                    <p class="text-sm!">No se ejecutó ninguna acción.</p>
                {/if}
                {#if caso.appended_messages.length}
                    <p class="font-semibold text-sm!">Mensajes después de la transferencia</p>
                    <ul class="space-y-2 text-sm">
                        {#each caso.appended_messages as mensaje}
                            <li class="bg-slate-50 p-2 rounded-lg">«{mensaje.text_redacted}» <span class="text-slate-400 text-xs">{formatearFecha(mensaje.received_at)}</span></li>
                        {/each}
                    </ul>
                {/if}
            </div>
        </div>
    </section>

    <section>
        <div class="bg-white p-4 rounded-2xl space-y-3">
            <h3 class="font-bold text-lg!">Evidencia</h3>
            <div class="overflow-x-auto">
                <table class="text-left text-sm w-full">
                    <thead class="text-slate-400 text-xs">
                        <tr><th class="py-1 pr-4">Llamada</th><th class="pr-4">Tool</th><th class="pr-4">Hora</th><th class="pr-4">Estado</th><th>Referencia</th></tr>
                    </thead>
                    <tbody class="font-mono text-xs">
                        {#each caso.evidence.tool_calls ?? [] as llamada}
                            <tr class="border-slate-100 border-t">
                                <td class="py-1 pr-4">{llamada.tool_call_id}</td><td class="pr-4">{llamada.tool}</td><td class="pr-4">{llamada.called_at}</td>
                                <td class="pr-4">{llamada.status}</td><td class="break-all">{llamada.result_ref}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
            <p class="text-sm!">
                Tarjetas: {(caso.evidence.cards ?? []).map((t) => `${t.card_id} (•••• ${t.last4})`).join(', ') || '—'} ·
                Transacciones: {(caso.evidence.transactions ?? []).join(', ') || '—'} ·
                Eventos de seguridad: {(caso.evidence.security_events ?? []).length}
            </p>
        </div>
    </section>

    <section>
        <div class="bg-white p-4 rounded-2xl space-y-4">
            <div class="flex flex-wrap gap-3 items-center justify-between">
                <h3 class="font-bold text-lg!">Audit trail de la conversación</h3>
                {#if data.auditoria}
                    <span class={`font-semibold px-3 py-1 rounded-full text-xs ${data.auditoria.cadena_valida ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                        {data.auditoria.cadena_valida ? 'Cadena de hashes verificada' : 'La cadena de hashes no verifica'} · {data.auditoria.total} eventos
                    </span>
                {/if}
            </div>
            <p class="font-mono text-xs!">{caso.conversation_ref}</p>

            {#if !data.auditoria}
                <p class="text-sm!">No se pudo leer el audit trail.</p>
            {/if}
            {#each turnos as [turno, eventos] (turno)}
                <details class="border border-slate-100 p-3 rounded-xl" open={turno > 0}>
                    <summary class="cursor-pointer font-semibold text-sm">Turno {turno}</summary>
                    <ul class="mt-2 space-y-1 text-xs">
                        {#each eventos as evento}
                            <li class="flex gap-2">
                                <span class="font-mono shrink-0 text-slate-400 w-28">{evento.event_type}</span>
                                <span class="break-words">
                                    {resumen(evento)}
                                    {#if evento.rule_ids?.length}<span class="font-mono text-slate-400"> [{evento.rule_ids.join(', ')}]</span>{/if}
                                    {#if evento.event_type === 'policy_decision' && campo(evento, 'reply')?.text_redacted}
                                        <span class="bg-slate-50 block mt-1 p-2 rounded-lg">Asistente: «{campo(evento, 'reply').text_redacted}»</span>
                                    {/if}
                                </span>
                            </li>
                        {/each}
                    </ul>
                </details>
            {/each}
        </div>
    </section>
</div>
