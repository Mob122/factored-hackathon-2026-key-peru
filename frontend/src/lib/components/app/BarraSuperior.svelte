<script lang="ts">
	import { page } from "$app/state";

    let { abrir = $bindable() }: {abrir: boolean} = $props();

    const usuario = $derived(page.data.usuario);
</script>

<header> 
    <div class="rounded-2xl z-30">
        <div class="flex gap-1 py-1 items-center justify-between">
            <button aria-label="Abrir menú" class="bg-white p-2 rounded-full text-slate-600 hover:bg-slate-100 lg:hidden" onclick={() => abrir = true}>
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    class="h-6 w-6"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M4 6h16M4 12h16M4 18h16"
                    />
                </svg>
            </button>

            <div class="hidden lg:block">
                <div class="bg-white rounded-3xl">
                    <div class="flex gap-2 items-center p-2">
                        <div class="bg-gray-100 p-1 rounded-full">
                            <svg class="h-5 stroke-gris-secundario/62 w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M16.6725 16.6412L21 21M19 11C19 15.4183 15.4183 19 11 19C6.58172 19 3 15.4183 3 11C3 6.58172 6.58172 3 11 3C15.4183 3 19 6.58172 19 11Z"  stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
                        </div>
                        <input class="outline-none" type="text" placeholder="Buscar tarjetas...">
                    </div>
                </div>
            </div>

            <div class="flex gap-4 items-center">
                <div class="bg-white hidden p-2 rounded-full lg:block">
                    <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M12.0009 5C13.4331 5 14.8066 5.50571 15.8193 6.40589C16.832 7.30606 17.4009 8.52696 17.4009 9.8C17.4009 11.7691 17.846 13.2436 18.4232 14.3279C19.1606 15.7133 19.5293 16.406 19.5088 16.5642C19.4849 16.7489 19.4544 16.7997 19.3026 16.9075C19.1725 17 18.5254 17 17.2311 17H6.77066C5.47638 17 4.82925 17 4.69916 16.9075C4.54741 16.7997 4.51692 16.7489 4.493 16.5642C4.47249 16.406 4.8412 15.7133 5.57863 14.3279C6.1558 13.2436 6.60089 11.7691 6.60089 9.8C6.60089 8.52696 7.16982 7.30606 8.18251 6.40589C9.19521 5.50571 10.5687 5 12.0009 5ZM12.0009 5V3M9.35489 20C10.0611 20.6233 10.9888 21.0016 12.0049 21.0016C13.0209 21.0016 13.9486 20.6233 14.6549 20" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
                </div>
                <div class="bg-white flex gap-3 items-center px-3 py-1 rounded-3xl md:px-4">
                    <div class="bg-red-500 flex font-bold h-9 items-center justify-center rounded-full shrink-0 text-sm text-white w-9">
                        {usuario?.nombre?.charAt(0)?.toUpperCase() ?? 'U'}
                    </div>
    
                    <div class="min-w-0 space-x-2">
                        <p class="font-semibold text-sm text-slate-800 truncate">
                            {usuario?.nombre ?? 'Usuario'}
                        </p>
    
                        <p class="text-slate-500 text-xs">
                            {usuario?.correo_electronico}
                        </p>
                    </div>            
                </div>
            </div>      
        </div>
    </div>
</header>