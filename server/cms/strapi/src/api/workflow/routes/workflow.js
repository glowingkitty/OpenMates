'use strict';

/**
 * workflow router
 */

const { createCoreRouter } = require('@strapi/strapi').factories;

module.exports = createCoreRouter('api::workflow.workflow');
