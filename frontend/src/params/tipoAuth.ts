import type { ParamMatcher } from '@sveltejs/kit';

export const match: ParamMatcher = (param): param is 'login' | 'registrarse' => {
    return param === 'login' || param === 'registrarse';
};