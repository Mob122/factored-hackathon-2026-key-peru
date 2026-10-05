<script lang="ts">
	import Microfono from '$lib/assets/icons/Microfono.svelte';
	import Seguridad from '$lib/assets/icons/Seguridad.svelte';
    import RobotPeru from '$lib/assets/robot-peru.webp';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let consulta = $state('');
    let enviando = $state(false);

    let mensajes = $state([
        {
            rol: 'ai',
            content: 'Hola. Soy tu asistente de tarjetas y transacciones. Puedo ayudarte a consultar tus tarjetas, revisar movimientos recientes o identificar un cargo.',
            time: 'Ahora'
        }
    ]);

    const sugerencias = [
        '¿Cuáles son mis tarjetas?',
        'Muéstrame mis últimas transacciones',
        '¿Cuál es el estado de mi tarjeta?',
        'Quiero consultar un cargo'
    ];

    function seleccionarSugerencia(texto: string) {
        consulta = texto;
    }

    async function enviarConsulta() {
        if (!consulta.trim() || enviando) return;

        const mensaje = consulta.trim();

        mensajes = [
            ...mensajes,
            {
                rol: 'user',
                content: mensaje,
                time: 'Ahora'
            }
        ];

        consulta = '';
        enviando = true;

        // TODO:
        // Aquí irá la llamada a tu orchestrator / API.
        // const response = await fetch('/api/consultas', ...)

        setTimeout(() => {
            mensajes = [
                ...mensajes,
                {
                    rol: 'ai',
                    content:
                        'Estoy procesando tu consulta. Esta respuesta será generada únicamente con información verificada de tu cuenta.',
                    time: 'Ahora'
                }
            ];

            enviando = false;
        }, 800);
    }

    function manejarEnter(event: KeyboardEvent) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            enviarConsulta();
        }
    }

    // Activar el micrófono y convertir voz a texto (opcional).
    // function activarMicrofono() {
    //    // Usar apiwebspeech para convertir voz a texto y asignar el resultado a la variable `consulta`.
    //    // Ejemplo:
    //      const recognition = new webkitSpeechRecognition();
    // }
</script>

<svelte:head>
    <title>Consultas | Agente</title>
</svelte:head>

<section class="flex flex-1 flex-col h-[calc(100vh-120px)] min-h-0 overflow-hidden">        
    <header class="bg-white flex items-center py-3 rounded-b-2xl shrink-0">
        <a class="group inline-block p-1!" aria-label="Volver" href="/app">
            <svg class="group-hover:stroke-white h-8 stroke-gris-secundario/62 transition-colors w-8" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M6 12H18M6 12L11 7M6 12L11 17"stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
        </a>
        <div class="flex gap-3 items-center">
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

    </header>

    <main class="flex-1 min-h-0 overflow-y-auto">        
        <div class="flex flex-col gap-4 p-4">
            {#each mensajes as mensaje}
                {#if mensaje.rol === 'ai'}
                    <div class="flex gap-3 items-start">
                        <figure>
                            <img class="aspect-square h-9 rounded-xl w-9" src={RobotPeru} alt="Avatar Robot Key Perú">
                        </figure>

                        <div class="max-w-[85%]">
                            <div class="bg-white border border-slate-200 px-5 py-4 rounded-2xl rounded-tl-md  shadow-sm">
                                <p class="leading-6 text-sm text-slate-700">{mensaje.content}</p>
                            </div>
                            <p class="mt-1 px-1 text-[11px] text-slate-400">{mensaje.time}</p>
                        </div>
                    </div>
                {:else}
                    <div class="flex justify-end">
                        <div class="max-w-[85%]">
                            <div class="px-5 py-4 rounded-2xl rounded-tr-md text-white">
                                <p class="leading-6 text-sm">{mensaje.content}</p>
                            </div>
                            <p class="mt-2 px-1 text-[11px] text-right text-slate-400">{mensaje.time}</p>
                        </div>
                    </div>
                    
                {/if}
            {/each}

            {#if enviando}
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
                {#if mensajes.length === 8}
                    <div class="mb-4">
                        <p class="font-medium mb-3 text-xs">
                            Puedes preguntarme, por ejemplo:
                        </p>
                        <div class="flex flex-wrap gap-2">
                            {#each sugerencias as sugerencia}

                                <button
                                    class="border border-slate-200 bg-white hover:border-red-500/30 hover:bg-red-500/5 hover:text-red-500 font-medium px-3 py-2  text-slate-600 text-xs transition rounded-full"
                                    onclick={() => seleccionarSugerencia(sugerencia)}
                                >
                                    {sugerencia}
                                </button>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
        </div>        

    </main>

    <footer class="flex items-center gap-2 shrink-0">        
        <div class="rounded-2xl border border-slate-200 bg-white focus-within:border-red-500/40 min-h-12 transition w-full">            
            <div class="flex gap-2 items-center pr-3">
                <textarea
                    bind:value={consulta}
                    onkeydown={manejarEnter}
                    disabled={enviando}
                    rows="1"
                    placeholder="Escribe tu consulta..."
                    class="bg-transparent border-0 disabled:opacity-50 resize-none outline-none placeholder:text-slate-400 px-3 py-3 text-slate-800 text-sm w-full"
                ></textarea>       
                <Microfono _class="fill-gris-secundario/62 h-5 w-5" />     
            </div>
        </div>
        <button
            onclick={enviarConsulta}
            disabled={!consulta.trim() || enviando}
            class="bg-red-500 disabled:cursor-not-allowed disabled:opacity-40 flex hover:bg-red-600 items-center justify-center min-h-12 rounded-2xl text-white transition w-14"
            aria-label="Enviar consulta"
        >
            <svg class="h-5 stroke-white w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M10.3009 13.6949L20.102 3.89742M10.5795 14.1355L12.8019 18.5804C13.339 19.6545 13.6075 20.1916 13.9458 20.3356C14.2394 20.4606 14.575 20.4379 14.8492 20.2747C15.1651 20.0866 15.3591 19.5183 15.7472 18.3818L19.9463 6.08434C20.2845 5.09409 20.4535 4.59896 20.3378 4.27142C20.2371 3.98648 20.013 3.76234 19.7281 3.66167C19.4005 3.54595 18.9054 3.71502 17.9151 4.05315L5.61763 8.2523C4.48114 8.64037 3.91289 8.83441 3.72478 9.15032C3.56153 9.42447 3.53891 9.76007 3.66389 10.0536C3.80791 10.3919 4.34498 10.6605 5.41912 11.1975L9.86397 13.42C10.041 13.5085 10.1295 13.5527 10.2061 13.6118C10.2742 13.6643 10.3352 13.7253 10.3876 13.7933C10.4468 13.87 10.491 13.9585 10.5795 14.1355Z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
        </button>        
    </footer>    
</section>


<!--    <main class="flex min-h-0 flex-1 flex-col bg-slate-50">        
        <div class="flex-1 overflow-y-auto">

            <div class="mx-auto flex w-full max-w-4xl flex-col gap-6 px-5 py-8 sm:px-8">


                <!-- Loading -->
               

            <!-- </div>

        </div> -->


        <!-- ============================================ -->
        <!-- SUGERENCIAS + INPUT -->
        <!-- ============================================ -->
<!-- 
         -->               

<!-- 
                </div>

            </div>

        </div>
    </main>

</div>  -->