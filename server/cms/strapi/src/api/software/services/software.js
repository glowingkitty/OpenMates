'use strict';

/**
 * software service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::software.software');
