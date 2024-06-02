'use strict';

/**
 * user-account service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::user-account.user-account');
