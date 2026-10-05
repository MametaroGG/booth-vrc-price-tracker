'use strict';

const MAX_TEXT = 512;
const SAFE_HEADERS = ['content-type', 'server', 'via', 'x-cache', 'retry-after'];

function safeUrl(value, base) {
    try {
        const url = new URL(String(value), base);
        if (!['http:', 'https:'].includes(url.protocol)) return '[non-HTTP URL omitted]';
        url.username = '';
        url.password = '';
        url.search = '';
        url.hash = '';
        return url.href.slice(0, 300);
    } catch { return '[unparseable URL omitted]'; }
}

function plainText(value, limit = MAX_TEXT) {
    let text = String(value ?? '').slice(0, 8192)
        .replace(/<script\b[^>]*>[\s\S]*?(?:<\/script\s*>|$)/gi, ' ')
        .replace(/<style\b[^>]*>[\s\S]*?(?:<\/style\s*>|$)/gi, ' ')
        .replace(/<!--[\s\S]*?(?:-->|$)/g, ' ')
        .replace(/<[^>]*(?:>|$)/g, ' ')
        .replace(/&(?:lt|gt|quot|apos|amp|nbsp);/gi, ' ')
        .replace(/&#(?:x[0-9a-f]+|\d+);/gi, ' ')
        .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
        .replace(/https?:\/\/[^\s<>"']+/gi, value => safeUrl(value));
    // Error bodies are optional. Prefer omission over accidentally preserving
    // credentials, session data, a bearer token, or an echoed authentication form.
    if (/\b(?:authorization|bearer|cookie|set-cookie|password|passwd|credential|secret|token|api[ _-]?key|csrf|session[ _-]?id)\b/i.test(text)) {
        return '[omitted: potentially sensitive diagnostic text]';
    }
    text = text.replace(/[A-Za-z0-9_+\/-]{24,}={0,2}/g, '[opaque value omitted]')
        .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email omitted]')
        .replace(/\s+/g, ' ').trim();
    return text.slice(0, limit);
}

function safeResponse(response) {
    if (!response) return null;
    const getHeader = key => response.headers?.get?.(key) ?? response.headers?.[key];
    const headers = {};
    for (const key of SAFE_HEADERS) {
        const value = getHeader(key);
        if (value !== undefined && value !== null) headers[key] = plainText(Array.isArray(value) ? value.join(', ') : value, 200);
    }
    const status = Number.isInteger(response.status) ? response.status : null;
    let errorBodyPrefix = null;
    if (status >= 400) {
        const type = String(getHeader('content-type') || '').toLowerCase();
        if (typeof response.data === 'string' && /^(?:text\/plain|text\/html)(?:\s*;|$)/.test(type)) {
            errorBodyPrefix = plainText(response.data);
        } else {
            errorBodyPrefix = '[omitted: non-plain-text/non-HTML or unknown content type]';
        }
    }
    return { status, headers, errorBodyPrefix };
}

module.exports = { MAX_TEXT, SAFE_HEADERS, plainText, safeResponse, safeUrl };
