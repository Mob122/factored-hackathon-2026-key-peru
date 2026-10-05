<script lang="ts">
	import { onMount, tick } from 'svelte';
	import Microfono from '$lib/assets/icons/Microfono.svelte';
	import Seguridad from '$lib/assets/icons/Seguridad.svelte';
    import RobotPeru from '$lib/assets/robot-peru.webp';
	import type { CodigoSms, EstadoChat, RespuestaChat } from '$lib/types';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    // Chat del cliente (docs/contracts/chat_api.md, sección 4). El navegador habla con /api/chat/*, que agrega el token.
    type Mensaje = { rol: 'ai' | 'user' | 'aviso'; texto: string; hora: string };
    type Guardado = {
        customer_id: string | null;
        sesion_id: string;
        conversacion: string;
        estado: EstadoChat;
        idioma: 'es' | 'pt';
        caso: string | null;
        pendiente: RespuestaChat['pending_confirmation'];
        mensajes: Mensaje[];
    };

    // La conversación vive en sessionStorage de la pestaña: así se retoma después de volver a iniciar sesión (4.6).
    const CLAVE = 'kp_chat';

    const TEXTOS = {
        es: {
            si: 'Sí', no: 'No',
            tarjeta: (ultimos4: string) => `La terminada en ${ultimos4}.`,
            codigoEnviado: 'Código enviado desde la ventana de verificación.',
            sugerencias: [
                '¿Cuál es mi saldo?',
                '¿Qué tarjetas tengo?',
                '¿Mi tarjeta de crédito está activa?',
                'Muéstrame los movimientos de mi tarjeta de crédito',
                'Perdí mi tarjeta de crédito, quiero bloquearla',
                'Quiero hablar con un asesor'
            ]
        },
        pt: {
            si: 'Sim', no: 'Não',
            tarjeta: (ultimos4: string) => `O final ${ultimos4}.`,
            codigoEnviado: 'Código enviado pela janela de verificação.',
            sugerencias: [
                'Qual é o meu saldo?',
                'Quais cartões eu tenho?',
                'Meu cartão de crédito está ativo?',
                'Quero ver os lançamentos do meu cartão de crédito',
                'Perdi meu cartão de crédito, quero bloquear',
                'Quero falar com um atendente'
            ]
        }
    };

    let conversacion = $state<string | null>(null);
    let estado = $state<EstadoChat>('IDLE');
    let idioma = $state<'es' | 'pt'>('es');
    let idiomaElegido = $state(false); // El cliente cambió el idioma: va en el próximo pedido (POL-GEN-03).
    let caso = $state<string | null>(null);
    let pendiente = $state<RespuestaChat['pending_confirmation']>(null);
    let mensajes = $state<Mensaje[]>([]);
    let consulta = $state('');
    let enviando = $state(false);
    let iniciando = $state(true);
    let error = $state('');

    // Ventana de verificación del step-up (4.3): el código nunca va en el texto del chat (POL-AUTH-08).
    let codigo = $state('');
    let sms = $state<CodigoSms | null>(null);
    let avisoSms = $state('');
    let pidiendoSms = $state(false);

    let ahora = $state(Date.now());
    let contenedor: HTMLElement | undefined = $state();

    const textos = $derived(TEXTOS[idioma]);
    const ultimaRespuesta = $derived([...mensajes].reverse().find((mensaje) => mensaje.rol === 'ai')?.texto ?? '');

    // SELECT_CARD: respuestas rápidas con los últimos 4 que nombra la respuesta ("terminada en 5070", "final 7858").
    const opcionesTarjeta = $derived(
        estado === 'SELECT_CARD'
            ? [...new Set([...ultimaRespuesta.matchAll(/(?:terminada en|final)\s+(\d{4})/gi)].map((m) => m[1]))]
            : []
    );
    const conSiNo = $derived(['OFFER_BLOCK', 'SELECT_TRANSACTION', 'AWAIT_CONFIRMATION'].includes(estado));
    const cerrada = $derived(estado === 'ENDED' || estado === 'SESSION_EXPIRED');
    const segundos = $derived(pendiente ? Math.max(0, Math.ceil((Date.parse(pendiente.expires_at) - ahora) / 1000)) : 0);
    const mostrarSugerencias = $derived(estado === 'IDLE' && mensajes.length === 1 && mensajes[0].rol === 'ai');

    $effect(() => {
        if (!pendiente) return;
        const intervalo = setInterval(() => (ahora = Date.now()), 1000);
        return () => clearInterval(intervalo);
    });

    onMount(() => {
        consulta = data.mensajeInicial;
        if (data.sesion.idioma) idioma = data.sesion.idioma;
        void arrancar();
    });

    const hora = () => new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });

    // Las listas de transacciones llegan en una línea con "- " antes de cada ítem (contrato, sección 1).
    const conLineas = (texto: string) => texto.replace(/ - /g, '\n- ');

    const mensajeDe = (datos: any) =>
        typeof datos?.detail === 'string' ? datos.detail : (datos?.detail?.mensaje ?? 'Ocurrió un error inesperado.');
    const codigoDe = (datos: any): string | undefined => datos?.detail?.codigo;

    async function llamar(accion: 'sesiones' | 'mensaje' | 'codigo', cuerpo?: object) {
        try {
            const respuesta = await fetch(`/api/chat/${accion}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(cuerpo ?? {})
            });
            return { status: respuesta.status, datos: await respuesta.json().catch(() => null) };
        } catch {
            return { status: 0, datos: { detail: { mensaje: 'No hay conexión con el servidor. Intente de nuevo.' } } };
        }
    }

    function guardar() {
        if (!conversacion) return;
        const guardado: Guardado = {
            customer_id: data.usuario?.customer_id ?? null, sesion_id: data.sesion.sesion_id, conversacion, estado, idioma,
            caso, pendiente, mensajes
        };
        try {
            sessionStorage.setItem(CLAVE, JSON.stringify(guardado));
        } catch {
            // Sin almacenamiento la conversación solo no se retoma tras un nuevo inicio de sesión.
        }
    }

    function leer(): Guardado | null {
        try {
            const guardado = JSON.parse(sessionStorage.getItem(CLAVE) ?? 'null') as Guardado | null;
            return guardado && guardado.customer_id === (data.usuario?.customer_id ?? null) ? guardado : null;
        } catch {
            return null;
        }
    }

    async function bajar() {
        await tick();
        contenedor?.scrollTo({ top: contenedor.scrollHeight, behavior: 'smooth' });
    }

    function agregar(rol: Mensaje['rol'], texto: string) {
        mensajes = [...mensajes, { rol, texto, hora: hora() }];
        guardar();
        void bajar();
    }

    function aplicar(respuesta: RespuestaChat) {
        conversacion = respuesta.conversation_id;
        estado = respuesta.state;
        idioma = respuesta.language;
        pendiente = respuesta.pending_confirmation;
        caso = respuesta.case_id ?? caso;
        if (pendiente) ahora = Date.now();
        if (estado !== 'STEP_UP') {
            codigo = '';
            sms = null;
            avisoSms = '';
        }
        agregar('ai', respuesta.reply);
    }

    function expirada() {
        estado = 'SESSION_EXPIRED';
        pendiente = null;
        sms = null;
        agregar('aviso', 'Su sesión expiró. Inicie sesión de nuevo para continuar esta conversación.');
    }

    async function arrancar() {
        const guardado = leer();
        let nota: string | null = null;

        if (guardado) {
            ({ conversacion, estado, idioma, caso, pendiente, mensajes } = guardado);

            // Misma sesión (volvió al chat desde otra página): la conversación sigue donde estaba.
            if (guardado.sesion_id === data.sesion.sesion_id && guardado.estado !== 'SESSION_EXPIRED') {
                iniciando = false;
                void bajar();
                return;
            }
            // Sesión nueva: se retoma la conversación (G-02); nada pendiente pasa a la sesión nueva (POL-AUTH-07).
            if (guardado.estado !== 'ENDED' && guardado.estado !== 'HANDED_OFF') {
                pendiente = null;
                const respuesta = await llamar('sesiones', { conversation_id: guardado.conversacion });
                if (respuesta.status === 201) {
                    aplicar(respuesta.datos);
                    iniciando = false;
                    return;
                }
                if (respuesta.status === 401) {
                    expirada();
                    iniciando = false;
                    return;
                }
                nota = 'No se pudo retomar la conversación anterior. Empezamos una nueva.';
            } else if (guardado.estado === 'HANDED_OFF' && guardado.caso) {
                nota = `Su conversación anterior quedó con un asesor (caso ${guardado.caso}). Puede verla en Mis casos.`;
            }
        }

        await nueva(nota);
        iniciando = false;
    }

    async function nueva(nota: string | null = null) {
        mensajes = [];
        conversacion = null;
        caso = null;
        pendiente = null;
        estado = 'IDLE';
        codigo = '';
        sms = null;
        error = '';
        if (nota) agregar('aviso', nota);

        enviando = true;
        const respuesta = await llamar('sesiones', idiomaElegido ? { idioma } : {});
        enviando = false;
        if (respuesta.status === 201) {
            idiomaElegido = false;
            aplicar(respuesta.datos);
        } else if (respuesta.status === 401) {
            expirada();
        } else {
            error = mensajeDe(respuesta.datos);
        }
    }

    async function turno(cuerpo: { conversation_id: string; mensaje?: string; codigo_step_up?: string; idioma?: string }) {
        enviando = true;
        error = '';
        if (idiomaElegido) cuerpo.idioma = idioma;
        const respuesta = await llamar('mensaje', cuerpo);
        enviando = false;

        if (respuesta.status === 200) {
            idiomaElegido = false;
            aplicar(respuesta.datos);
        } else if (respuesta.status === 401) {
            expirada();
        } else {
            const codigoError = codigoDe(respuesta.datos);
            error = ['CONVERSATION_NOT_FOUND', 'CONVERSATION_FORBIDDEN', 'SESSION_NOT_ATTACHED'].includes(codigoError ?? '')
                ? 'Esta conversación ya no está disponible. Empiece una nueva conversación.'
                : mensajeDe(respuesta.datos);
        }
    }

    async function enviar(texto = consulta.trim()) {
        if (!texto || enviando || !conversacion || cerrada) return;
        if (texto === consulta.trim()) consulta = '';
        agregar('user', texto);
        await turno({ conversation_id: conversacion, mensaje: texto });
    }

    async function enviarCodigo() {
        if (!/^\d{6}$/.test(codigo) || enviando || !conversacion) return;
        const valor = codigo;
        codigo = '';
        agregar('user', `🔒 ${textos.codigoEnviado}`);
        await turno({ conversation_id: conversacion, codigo_step_up: valor });
    }

    // SMS simulado del IdP de prueba (POL-AUTH-14): solo en desarrollo y mientras la conversación está en STEP_UP.
    async function pedirSms() {
        pidiendoSms = true;
        avisoSms = '';
        const respuesta = await llamar('codigo');
        pidiendoSms = false;

        if (respuesta.status === 201) {
            sms = respuesta.datos;
        } else if (respuesta.status === 401) {
            expirada();
        } else {
            avisoSms = codigoDe(respuesta.datos) === 'DEMO_OTP_DISABLED'
                ? 'En este entorno no hay SMS simulado: el código lo emite la consola del jurado.'
                : mensajeDe(respuesta.datos);
        }
    }

    function manejarEnter(event: KeyboardEvent) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            enviar();
        }
    }

    const formatoReloj = (total: number) => `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
</script>

<svelte:head>
    <title>Consultas | Agente</title>
</svelte:head>

<section class="flex flex-1 flex-col h-[calc(100vh-120px)] min-h-0 overflow-hidden">
    <header class="bg-white flex flex-wrap gap-2 items-center py-3 pr-3 rounded-b-2xl shrink-0">
        <a class="group inline-block p-1!" aria-label="Volver" href="/app">
            <svg class="group-hover:stroke-white h-8 stroke-gris-secundario/62 transition-colors w-8" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M6 12H18M6 12L11 7M6 12L11 17"stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
        </a>
        <div class="flex flex-1 gap-3 items-center">
            <figure>
                <img class="aspect-square h-5 rounded-full w-5" src={RobotPeru} alt="Avatar Robot Key Perú">
            </figure>

            <div>
                <div class="flex gap-2 items-center">
                    <p class="font-bold">Multi-Agente KP</p>
                    <Seguridad _class="fill-gris-secundario/62 h-5 w-5" />
                </div>
                <span class="text-[0.8rem]">Online • Key Perú</span>
            </div>
        </div>

        <label class="sr-only" for="idioma">Idioma</label>
        <select id="idioma" bind:value={idioma} onchange={() => (idiomaElegido = true)} class="bg-slate-50 px-2 py-1.5 rounded-lg text-sm">
            <option value="es">Español</option>
            <option value="pt">Português</option>
        </select>
        <button class="border border-slate-200 cursor-pointer disabled:opacity-50 font-semibold hover:bg-red-50 px-3 py-1.5 rounded-lg text-sm" disabled={enviando || iniciando} onclick={() => nueva()}>
            Nueva conversación
        </button>
    </header>

    <!-- La página ya está dentro del <main> del layout. aria-live anuncia las respuestas nuevas. -->
    <div class="flex-1 min-h-0 overflow-y-auto" bind:this={contenedor} aria-live="polite" data-transcripcion>
        <div class="flex flex-col gap-4 p-4">
            {#each mensajes as mensaje}
                {#if mensaje.rol === 'ai'}
                    <div class="flex gap-3 items-start">
                        <figure>
                            <img class="aspect-square h-9 rounded-xl w-9" src={RobotPeru} alt="Avatar Robot Key Perú">
                        </figure>

                        <div class="max-w-[85%]">
                            <div class="bg-white border border-slate-200 px-5 py-4 rounded-2xl rounded-tl-md  shadow-sm">
                                <p class="leading-6 text-sm! text-slate-700! whitespace-pre-line">{conLineas(mensaje.texto)}</p>
                            </div>
                            <p class="mt-1 px-1 text-[11px] text-slate-400">{mensaje.hora}</p>
                        </div>
                    </div>
                {:else if mensaje.rol === 'user'}
                    <div class="flex justify-end">
                        <div class="max-w-[85%]">
                            <div class="bg-red-500 px-5 py-4 rounded-2xl rounded-tr-md text-white">
                                <p class="leading-6 text-sm! text-white!">{mensaje.texto}</p>
                            </div>
                            <p class="mt-2 px-1 text-[11px] text-right text-slate-400">{mensaje.hora}</p>
                        </div>
                    </div>
                {:else}
                    <p class="bg-amber-50 mx-auto px-4 py-2 rounded-xl text-amber-800! text-center text-xs!">{mensaje.texto}</p>
                {/if}
            {/each}

            {#if enviando || iniciando}
                <div class="flex gap-3 items-start">
                    <figure>
                        <img class="aspect-square h-9 rounded-xl w-9" src={RobotPeru} alt="Avatar Robot Key Perú">
                    </figure>

                    <div class="border border-slate-200 bg-white px-5 py-4 rounded-2xl rounded-tl-md">

                        <div class="flex gap-1.5 items-center">
                            <span class="animate-bounce  bg-slate-400 h-2 rounded-full w-2"></span>
                            <span
                                class="animate-bounce [animation-delay:100ms] h-2 rounded-full bg-slate-400 w-2"
                            ></span>
                            <span
                                class="animate-bounce [animation-delay:200ms] h-2 rounded-full bg-slate-400 w-2"
                            ></span>
                        </div>
                    </div>
                </div>
            {/if}


            <div class="mx-auto w-full">
                {#if mostrarSugerencias}
                    <div class="mb-4">
                        <p class="font-medium mb-3 text-xs">
                            Puedes preguntarme, por ejemplo:
                        </p>
                        <div class="flex flex-wrap gap-2">
                            {#each textos.sugerencias as sugerencia}

                                <button
                                    class="border border-slate-200 bg-white cursor-pointer hover:border-red-500/30 hover:bg-red-500/5 hover:text-red-500 font-medium px-3 py-2  text-slate-600 text-xs transition rounded-full"
                                    onclick={() => enviar(sugerencia)}
                                >
                                    {sugerencia}
                                </button>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
        </div>

    </div>

    <!-- Paneles según el estado de la conversación (contrato, sección 4.2). -->
    <div class="shrink-0 space-y-2 py-2">
        {#if error}
            <div class="bg-red-50 px-4 py-2 rounded-xl text-red-700 text-sm">{error}</div>
        {/if}

        {#if estado === 'STEP_UP'}
            <div class="bg-white border border-slate-200 p-4 rounded-2xl space-y-3">
                <div class="flex gap-2 items-center">
                    <Seguridad _class="fill-red-500 h-5 w-5" />
                    <p class="font-semibold text-slate-800 text-sm">Verificación adicional</p>
                </div>
                <p class="text-xs">Ingrese el código de 6 dígitos aquí. Nunca lo escriba en el chat.</p>
                <form class="flex gap-2" onsubmit={(event) => { event.preventDefault(); enviarCodigo(); }}>
                    <input
                        bind:value={codigo}
                        inputmode="numeric"
                        autocomplete="one-time-code"
                        maxlength="6"
                        placeholder="000000"
                        aria-label="Código de verificación"
                        class="bg-slate-50 font-mono outline-none px-3 py-2 rounded-xl text-lg tracking-[0.4em] w-40 focus:ring-2 focus:ring-red-100"
                    />
                    <button type="submit" disabled={!/^\d{6}$/.test(codigo) || enviando} class="bg-red-500 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40 font-semibold hover:bg-red-600 px-4 py-2 rounded-xl text-sm text-white">
                        Verificar
                    </button>
                </form>

                {#if sms}
                    <div class="bg-slate-900 max-w-sm p-3 rounded-xl text-white">
                        <p class="text-[11px]! text-slate-300!">SMS simulado · vence {new Date(sms.expira_en).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}</p>
                        <p class="mt-1 text-sm! text-white!">Su código de verificación Key Perú es <span class="font-bold font-mono tracking-widest">{sms.codigo}</span></p>
                        <button class="cursor-pointer mt-2 text-red-300 text-xs underline" onclick={() => (codigo = sms?.codigo ?? '')}>Usar este código</button>
                    </div>
                    <p class="text-[11px]! text-slate-400!">{sms.aviso}</p>
                {:else}
                    <button class="cursor-pointer disabled:opacity-50 font-semibold text-red-600 text-xs underline" disabled={pidiendoSms} onclick={pedirSms}>
                        {pidiendoSms ? 'Enviando…' : 'Recibir el código por SMS simulado'}
                    </button>
                {/if}
                {#if avisoSms}
                    <p class="text-amber-700! text-xs!">{avisoSms}</p>
                {/if}
            </div>
        {/if}

        {#if estado === 'AWAIT_CONFIRMATION' && pendiente}
            <div class="bg-white border border-red-200 flex flex-wrap gap-3 items-center justify-between p-4 rounded-2xl">
                <div>
                    <p class="font-semibold text-slate-800 text-sm">Confirmar bloqueo: {pendiente.card_type} •••• {pendiente.card_last4}</p>
                    <p class="text-xs">
                        {segundos > 0 ? `La confirmación vence en ${formatoReloj(segundos)}.` : 'La confirmación venció: cualquier respuesta la cancela.'}
                    </p>
                </div>
            </div>
        {/if}

        {#if estado === 'HANDED_OFF'}
            <div class="bg-white border border-slate-200 p-4 rounded-2xl text-sm">
                {#if caso}
                    <p><span class="font-semibold text-slate-800">Caso {caso}.</span> Un asesor continuará la atención. Lo que escriba aquí se agregará a su caso.</p>
                {:else}
                    <p>Un asesor continuará la atención. No hay número de caso todavía.</p>
                {/if}
                <a class="font-semibold inline-block mt-1 text-red-600 underline" href="/app/casos">Ver mis casos</a>
            </div>
        {/if}

        {#if estado === 'ENDED'}
            <div class="bg-white border border-slate-200 flex flex-wrap gap-3 items-center justify-between p-4 rounded-2xl text-sm">
                <p>La conversación terminó.</p>
                <button class="bg-red-500 cursor-pointer font-semibold hover:bg-red-600 px-4 py-2 rounded-xl text-white" onclick={() => nueva()}>Nueva conversación</button>
            </div>
        {/if}

        {#if estado === 'SESSION_EXPIRED'}
            <form method="POST" action="/logout?volver=/app/consultas" class="bg-white border border-slate-200 flex flex-wrap gap-3 items-center justify-between p-4 rounded-2xl text-sm">
                <p>Su sesión expiró. Al iniciar sesión de nuevo, retomamos esta conversación.</p>
                <button type="submit" class="bg-red-500 cursor-pointer font-semibold hover:bg-red-600 px-4 py-2 rounded-xl text-white">Iniciar sesión</button>
            </form>
        {/if}

        {#if !enviando && (opcionesTarjeta.length || conSiNo)}
            <div class="flex flex-wrap gap-2">
                {#each opcionesTarjeta as ultimos4}
                    <button class="bg-white border border-slate-200 cursor-pointer font-medium hover:border-red-500/30 hover:text-red-500 px-3 py-2 rounded-full text-xs" onclick={() => enviar(textos.tarjeta(ultimos4))}>
                        •••• {ultimos4}
                    </button>
                {/each}
                {#if conSiNo}
                    <button class="bg-white border border-slate-200 cursor-pointer font-medium hover:border-red-500/30 hover:text-red-500 px-4 py-2 rounded-full text-xs" onclick={() => enviar(textos.si)}>{textos.si}</button>
                    <button class="bg-white border border-slate-200 cursor-pointer font-medium hover:border-red-500/30 hover:text-red-500 px-4 py-2 rounded-full text-xs" onclick={() => enviar(textos.no)}>{textos.no}</button>
                {/if}
            </div>
        {/if}
    </div>

    <footer class="flex items-center gap-2 shrink-0">
        <div class="rounded-2xl border border-slate-200 bg-white focus-within:border-red-500/40 min-h-12 transition w-full">
            <div class="flex gap-2 items-center pr-3">
                <textarea
                    bind:value={consulta}
                    onkeydown={manejarEnter}
                    disabled={enviando || iniciando || cerrada}
                    rows="1"
                    placeholder={cerrada ? 'La conversación está cerrada' : 'Escribe tu consulta...'}
                    class="bg-transparent border-0 disabled:opacity-50 resize-none outline-none placeholder:text-slate-400 px-3 py-3 text-slate-800 text-sm w-full"
                ></textarea>
                <Microfono _class="fill-gris-secundario/62 h-5 w-5" />
            </div>
        </div>
        <button
            onclick={() => enviar()}
            disabled={!consulta.trim() || enviando || iniciando || cerrada}
            class="bg-red-500 disabled:cursor-not-allowed disabled:opacity-40 flex hover:bg-red-600 items-center justify-center min-h-12 rounded-2xl text-white transition w-14"
            aria-label="Enviar consulta"
        >
            <svg class="h-5 stroke-white w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M10.3009 13.6949L20.102 3.89742M10.5795 14.1355L12.8019 18.5804C13.339 19.6545 13.6075 20.1916 13.9458 20.3356C14.2394 20.4606 14.575 20.4379 14.8492 20.2747C15.1651 20.0866 15.3591 19.5183 15.7472 18.3818L19.9463 6.08434C20.2845 5.09409 20.4535 4.59896 20.3378 4.27142C20.2371 3.98648 20.013 3.76234 19.7281 3.66167C19.4005 3.54595 18.9054 3.71502 17.9151 4.05315L5.61763 8.2523C4.48114 8.64037 3.91289 8.83441 3.72478 9.15032C3.56153 9.42447 3.53891 9.76007 3.66389 10.0536C3.80791 10.3919 4.34498 10.6605 5.41912 11.1975L9.86397 13.42C10.041 13.5085 10.1295 13.5527 10.2061 13.6118C10.2742 13.6643 10.3352 13.7253 10.3876 13.7933C10.4468 13.87 10.491 13.9585 10.5795 14.1355Z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
        </button>
    </footer>
</section>
