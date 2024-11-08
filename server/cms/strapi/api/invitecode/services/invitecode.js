'use strict';

/**
 * invitecode service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::invitecode.invitecode');
