<script lang="ts">
	import { browser } from '$app/env';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

     const correoGuardado = browser ? localStorage.getItem('correo_electronico') : null;


    let formularioBase = $state({
        correo_electronico: correoGuardado ?? '',
        password: '',
        remember: !!correoGuardado
    });

    let formularioRegistro = $derived({nombre: ''});

    let verPassword = $state(false);

    let cargando = $state(false);
    let error = $state('');
    
    const enviarFormulario = async (event: SubmitEvent) => {
        event.preventDefault();

        if (!browser) return null;

        error = '';
        cargando = true;
        
        try {
            const response = await fetch('api/auth?tipoAuth=' + page.params.tipoAuth, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(page.params.tipoAuth === 'registrarse' ? {
                    correo_electronico: formularioBase.correo_electronico, 
                    password: formularioBase.password,
                    nombre: formularioRegistro.nombre
                } : {
                    correo_electronico: formularioBase.correo_electronico, 
                    password: formularioBase.password               
                })
            });
    
            const body = await response.json();

            if (!response.ok) {
                error = body.detail ??  body.error ?? 'Ocurrió un error inesperado. Por favor, inténtalo de nuevo.';
                return;
            }

            if  ( page.params.tipoAuth === 'login' ) {
                if (formularioBase.remember) {
                    localStorage.setItem('correo_electronico', formularioBase.correo_electronico);
                } else {
                    localStorage.removeItem('correo_electronico');
                }            
    
                goto('/app',{
                    invalidateAll: true
                });
            } else if ( page.params.tipoAuth === 'registrarse' ) {
                goto('/login',{
                    invalidateAll: true
                });
            }                        
        } catch (err) {
            error = 'Ocurrió un error inesperado. Por favor, inténtalo de nuevo.';
        } finally {
            console.log(error);
            
            cargando = false;
        }        
    };
</script>
     
<div>
    <div class="from-red-500 bg-linear-180 from-50% rounded-xl to-white to-53%">
        <div class="flex flex-col items-center max-w-125 mx-auto pb-4 pt-8">
            <div class="space-y-2">
                <svg class="fill-white h-17 mx-auto w-17" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path fill-rule="evenodd" clip-rule="evenodd" d="M10.5 9C12.9853 9 15 6.98528 15 4.5C15 2.01472 12.9853 0 10.5 0C8.01475 0 6.00003 2.01472 6.00003 4.5C6.00003 5.38054 6.25294 6.20201 6.69008 6.89574L0.585815 13L3.58292 15.9971L4.99714 14.5829L3.41424 13L5.00003 11.4142L6.58292 12.9971L7.99714 11.5829L6.41424 10L8.10429 8.30995C8.79801 8.74709 9.61949 9 10.5 9ZM10.5 7C11.8807 7 13 5.88071 13 4.5C13 3.11929 11.8807 2 10.5 2C9.11932 2 8.00003 3.11929 8.00003 4.5C8.00003 5.88071 9.11932 7 10.5 7Z"></path> </g></svg>
                <h2 class="font-bold text-white">{page.params.tipoAuth === 'registrarse' ? 'Crear una Cuenta' : 'Iniciar Sesión'}</h2>
            </div>
            <div class="p-2 w-full">
                <form onsubmit={enviarFormulario} class="bg-white mt-8 px-4 py-8 rounded-xl">
                    {#if page.params.tipoAuth === 'registrarse'}
                        <div class="mb-4 space-y-2">
                            <label for="nombre" class="block font-medium text-gray-700 text-sm">Nombre</label>
                            <input type="text" id="nombre" bind:value={formularioRegistro.nombre} required class="bg-gray-100 focus:ring focus:ring-gray-500 outline-none p-2 rounded-md shadow-xs w-full" />
                        </div>
                    {/if}
            
                    <div class="mb-4 space-y-2">
                        <label for="correo_electronico" class="block font-medium text-gray-700 text-sm">Correo electrónico</label>
                        <input type="email" id="correo_electronico" bind:value={formularioBase.correo_electronico} required class="bg-gray-100 focus:ring focus:ring-gray-500 outline-none p-2 rounded-md shadow-xs w-full" />
                    </div>
            
                    <div class="mb-4 space-y-2">
                        <label for="password" class="block font-medium text-gray-700 text-sm">Contraseña</label>
                        <div class="relative">
                            <input type={verPassword ? "text" : "password"} id="password" bind:value={formularioBase.password} required class="bg-gray-100 focus:ring focus:ring-gray-500 outline-none p-2 rounded-md shadow-xs w-full" />
                            {#if verPassword}
                                <button  aria-label="Ocultar contraseña" type="button" class="absolute cursor-pointer h-full px-3 right-0 top-0" onclick={() => verPassword = false}>
                                    <svg class="h-5 stroke-gris-secundario w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M2.99902 3L20.999 21M9.8433 9.91364C9.32066 10.4536 8.99902 11.1892 8.99902 12C8.99902 13.6569 10.3422 15 11.999 15C12.8215 15 13.5667 14.669 14.1086 14.133M6.49902 6.64715C4.59972 7.90034 3.15305 9.78394 2.45703 12C3.73128 16.0571 7.52159 19 11.9992 19C13.9881 19 15.8414 18.4194 17.3988 17.4184M10.999 5.04939C11.328 5.01673 11.6617 5 11.9992 5C16.4769 5 20.2672 7.94291 21.5414 12C21.2607 12.894 20.8577 13.7338 20.3522 14.5" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
                                </button>
                            {/if}
                            {#if !verPassword}
                                <button aria-label="Mostrar contraseña" type="button" class="absolute cursor-pointer h-full px-3 right-0 top-0" onclick={() => verPassword = true}>
                                    <svg class="h-5 stroke-gris-secundario w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M15.0007 12C15.0007 13.6569 13.6576 15 12.0007 15C10.3439 15 9.00073 13.6569 9.00073 12C9.00073 10.3431 10.3439 9 12.0007 9C13.6576 9 15.0007 10.3431 15.0007 12Z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> <path d="M12.0012 5C7.52354 5 3.73326 7.94288 2.45898 12C3.73324 16.0571 7.52354 19 12.0012 19C16.4788 19 20.2691 16.0571 21.5434 12C20.2691 7.94291 16.4788 5 12.0012 5Z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
                                </button>
                            {/if}
                        </div>
                    </div>
            
                    <div class="flex items-center mb-4">
                        <input type="checkbox" id="remember" bind:checked={formularioBase.remember} class="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded" />
                        <label for="remember" class="ml-2 block text-sm text-gray-900">Recordarme</label>
                    </div>
            
                    {#if error}
                        <div class="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-600">
                            {error}
                        </div>
                    {/if}
            
                    <button type="submit" class="bg-gris-secundario cursor-pointer hover:bg-gray-200 hover:text-gris-secundario p-2 rounded-2xl text-white transition-colors w-full">{page.params.tipoAuth === 'registrarse' ? 'Crear Cuenta' : 'Iniciar Sesión'}</button>                
                </form>

            
                
                <p class="flex gap-1 items-center justify-center text-sm text-gray-600 hover:text-gray-900">
                    {#if page.params.tipoAuth === 'registrarse'}
                        Ya tienes una cuenta? <a href="/login" class="p-2! text-gris-secundario">Inicia sesión</a>
                    {:else}
                        No tienes una cuenta? <a href="/registrarse" class="p-2! text-gris-secundario">Crea una cuenta</a>
                    {/if}
                </p>
                
            </div>
        </div>
    </div>
</div>
    

    