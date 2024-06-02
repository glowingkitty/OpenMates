'use strict';

/**
 * mate-config service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::mate-config.mate-config');
