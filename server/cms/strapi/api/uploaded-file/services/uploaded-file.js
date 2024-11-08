'use strict';

/**
 * uploaded-file service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::uploaded-file.uploaded-file');
