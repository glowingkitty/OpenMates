'use strict';

/**
 * workflow controller
 */

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::workflow.workflow');
