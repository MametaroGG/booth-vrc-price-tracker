'use strict';
// Offline test preload. Any accidental network attempt fails before a socket.
for (const protocol of ['node:http', 'node:https']) {
    const module = require(protocol);
    module.request = module.get = () => { throw new Error('NETWORK FORBIDDEN IN OFFLINE VALIDATION'); };
}
require('node:net').Socket.prototype.connect = function () {
    throw new Error('NETWORK FORBIDDEN IN OFFLINE VALIDATION');
};
globalThis.fetch = async () => { throw new Error('NETWORK FORBIDDEN IN OFFLINE VALIDATION'); };
