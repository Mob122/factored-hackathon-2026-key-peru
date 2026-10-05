import Ayuda from '$lib/assets/icons/Ayuda.svelte';
import Caso from '$lib/assets/icons/Caso.svelte';
import Consulta from '$lib/assets/icons/Consulta.svelte';
import Menu from '$lib/assets/icons/Menu.svelte';
import Tarjeta from '$lib/assets/icons/Tarjeta.svelte';
import Transaccion from '$lib/assets/icons/Transaccion.svelte';
import Seguridad from '$lib/assets/icons/Seguridad.svelte';

import type { Component } from 'svelte';

export type Rutas = Record<string, { texto: string; enlace: string, icono?: Component<{ _class: string | string[] }> }[]>;

export const RUTAS: Rutas = {
    RutasPrincipales: [
        { enlace: '/app', texto: 'Resumen', icono: Menu },
        { enlace: '/app/consultas', texto: 'Consultas', icono: Consulta },
        { enlace: '/app/tarjetas', texto: 'Mis tarjetas', icono: Tarjeta },
        { enlace: '/app/transacciones', texto: 'Transacciones', icono: Transaccion },
    ],
    RutasAtencion: [
        { enlace: '/app/casos', texto: 'Mis Casos', icono: Caso },
        { enlace: '/app/ayuda', texto: 'Ayuda', icono: Ayuda }
    ],
    RutasSeguridad: [
        { enlace: '/app/actividad', texto: 'Actividad y seguridad', icono: Seguridad },
    ]
};

// Agente humano: solo la bandeja de casos (contrato chat_api.md, sección 5).
export const RUTAS_AGENTE: Rutas = {
    RutasPrincipales: [
        { enlace: '/app/bandeja', texto: 'Bandeja de casos', icono: Caso },
    ],
    RutasAtencion: [],
    RutasSeguridad: []
};

// Jurado o usuario registrado sin cliente: un aviso en /app.
export const RUTAS_SIN_CLIENTE: Rutas = {
    RutasPrincipales: [
        { enlace: '/app', texto: 'Inicio', icono: Menu },
    ],
    RutasAtencion: [
        { enlace: '/app/ayuda', texto: 'Ayuda', icono: Ayuda }
    ],
    RutasSeguridad: []
};
