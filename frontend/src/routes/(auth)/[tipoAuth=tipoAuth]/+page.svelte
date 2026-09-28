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
    <h1>{page.params.tipoAuth === 'registrarse' ? 'Registrarse' : 'Iniciar Sesión'}</h1>

    <form onsubmit={enviarFormulario} class="mt-8">
        {#if page.params.tipoAuth === 'registrarse'}
            <div class="mb-4">
                <label for="nombre" class="block text-sm font-medium text-gray-700">Nombre</label>
                <input type="text" id="nombre" bind:value={formularioRegistro.nombre} required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
        {/if}

        <div class="mb-4">
            <label for="correo_electronico" class="block text-sm font-medium text-gray-700">Correo electrónico</label>
            <input type="email" id="correo_electronico" bind:value={formularioBase.correo_electronico} required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
        </div>

        <div class="mb-4">
            <label for="password" class="block text-sm font-medium text-gray-700">Contraseña</label>
            <input type="password" id="password" bind:value={formularioBase.password} required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
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

        <button type="submit" class="w-full bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">Enviar</button>                
    </form>
</div>
    

    