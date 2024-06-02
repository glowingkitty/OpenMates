'use strict';

/**
 * software controller
 */

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::software.software');
