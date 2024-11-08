'use strict';

/**
 * workflow service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::workflow.workflow');
