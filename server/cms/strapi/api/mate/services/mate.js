'use strict';

/**
 * mate service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::mate.mate');
