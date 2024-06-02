'use strict';

/**
 * invoice controller
 */

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::invoice.invoice');
