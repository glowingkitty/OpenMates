'use strict';

/**
 * app controller
 */

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::app.app');
