"""Generated OpenMates SDK app-skill namespaces.

Source: backend app metadata files
Regenerate with: python3 scripts/generate_sdk_app_skills.py
"""

from __future__ import annotations

from typing import Any, Callable

APP_SKILL_METADATA = [{'app_id': 'ai',
  'app_namespace_py': 'ai',
  'app_namespace_ts': 'ai',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'ai.ask.description',
  'schema': {'properties': {'conversation': {'description': 'Optional run-local conversation name '
                                                            'for retaining previous Workflow AI '
                                                            'context in the same run.',
                                             'type': 'string'},
                            'prompt': {'description': 'The question or task for the Workflow AI '
                                                      'step.',
                                       'type': 'string'}},
             'required': ['prompt'],
             'type': 'object'},
  'skill_id': 'ask',
  'skill_method_py': 'ask',
  'skill_method_ts': 'ask'},
 {'app_id': 'books',
  'app_namespace_py': 'books',
  'app_namespace_ts': 'books',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'books.translate.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'translate',
  'skill_method_py': 'translate',
  'skill_method_ts': 'translate'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Search GitHub repositories. Use this instead of web.search whenever the user '
                 'asks to find GitHub repos, repositories, open-source libraries, starred repos, '
                 'or repo examples by topic, language, framework, or project need. Returns '
                 'licensed repository embeds. Costs 10 credits per search.',
  'description_key': 'code.search_repos.description',
  'schema': {'properties': {'requests': {'description': 'Array of repository search requests. Each '
                                                        'request searches GitHub for public '
                                                        'licensed repositories matching the '
                                                        'query.\n',
                                         'items': {'properties': {'count': {'default': 6,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'repositories '
                                                                                           'to '
                                                                                           'return.',
                                                                            'maximum': 10,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'query': {'description': 'Repository '
                                                                                           'search '
                                                                                           'query, '
                                                                                           'e.g. '
                                                                                           '"svelte '
                                                                                           'markdown '
                                                                                           'editor", '
                                                                                           '"python '
                                                                                           'cli '
                                                                                           'framework", '
                                                                                           'or '
                                                                                           '"rust '
                                                                                           'web '
                                                                                           'server".\n',
                                                                            'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_repos',
  'skill_method_py': 'search_repos',
  'skill_method_ts': 'searchRepos'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Get latest documentation for programming libraries, frameworks, APIs, SDKs. Use '
                 'for ANY programming-related query about a specific library or framework.',
  'description_key': 'code.get_docs.description',
  'schema': {'properties': {'library': {'description': 'Library name to search for (e.g., "Svelte '
                                                       '5", "React", "FastAPI", "Miro API", '
                                                       'etc.).\n',
                                        'type': 'string'},
                            'question': {'description': 'Natural language question about the '
                                                        'documentation needed\n'
                                                        '(e.g., "How to use useState hook?", "How '
                                                        'to setup routing?").\n',
                                         'type': 'string'}},
             'required': ['library', 'question'],
             'type': 'object'},
  'skill_id': 'get_docs',
  'skill_method_py': 'get_docs',
  'skill_method_ts': 'getDocs'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'code.clean_repo.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'clean_repo',
  'skill_method_py': 'clean_repo',
  'skill_method_ts': 'cleanRepo'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'code.get_issues.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'get_issues',
  'skill_method_py': 'get_issues',
  'skill_method_ts': 'getIssues'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'code.add_issue.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'add_issue',
  'skill_method_py': 'add_issue',
  'skill_method_ts': 'addIssue'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'code.remove_secrets.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'remove_secrets',
  'skill_method_py': 'remove_secrets',
  'skill_method_ts': 'removeSecrets'},
 {'app_id': 'code',
  'app_namespace_py': 'code',
  'app_namespace_ts': 'code',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'code.get_project_overview.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'get_project_overview',
  'skill_method_py': 'get_project_overview',
  'skill_method_ts': 'getProjectOverview'},
 {'app_id': 'design',
  'app_namespace_py': 'design',
  'app_namespace_ts': 'design',
  'description': 'Search for free SVG icons for UI, product, interface, or graphic design. Use '
                 'this when the user asks to find icons by name, concept, object, or action. Do '
                 'not use it for brand-logo search or generated icon creation.',
  'description_key': 'app_skills.design.search_icons.description',
  'schema': {'properties': {'requests': {'description': 'Array of icon search requests backed by '
                                                        'Iconify.',
                                         'items': {'properties': {'count': {'default': 24,
                                                                            'description': 'Maximum '
                                                                                           'number '
                                                                                           'of '
                                                                                           'icon '
                                                                                           'results '
                                                                                           'to '
                                                                                           'return.',
                                                                            'maximum': 50,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'exclude_prefixes': {'description': 'Optional '
                                                                                                      'Iconify '
                                                                                                      'collection '
                                                                                                      'prefixes '
                                                                                                      'to '
                                                                                                      'exclude.',
                                                                                       'items': {'type': 'string'},
                                                                                       'type': 'array'},
                                                                  'include_prefixes': {'description': 'Optional '
                                                                                                      'Iconify '
                                                                                                      'collection '
                                                                                                      'prefixes '
                                                                                                      'to '
                                                                                                      'include.',
                                                                                       'items': {'type': 'string'},
                                                                                       'type': 'array'},
                                                                  'license_policy': {'default': 'permissive',
                                                                                     'description': 'Filter '
                                                                                                    'to '
                                                                                                    'permissive/no-attribution '
                                                                                                    'licenses '
                                                                                                    'by '
                                                                                                    'default.',
                                                                                     'enum': ['permissive',
                                                                                              'all'],
                                                                                     'type': 'string'},
                                                                  'query': {'description': 'Search '
                                                                                           'query, '
                                                                                           'e.g. '
                                                                                           '"home", '
                                                                                           '"calendar", '
                                                                                           'or '
                                                                                           '"settings".',
                                                                            'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_icons',
  'skill_method_py': 'search_icons',
  'skill_method_ts': 'searchIcons'},
 {'app_id': 'electronics',
  'app_namespace_py': 'electronics',
  'app_namespace_ts': 'electronics',
  'description': 'Use this skill when the user asks to find electronic components, especially '
                 'power converters or voltage regulators matching input voltage, output voltage, '
                 'output current, efficiency, BOM cost, footprint, or topology requirements. '
                 'Currently supports category power_converters via Texas Instruments WEBENCH Power '
                 'Designer.',
  'description_key': 'electronics.search_components.description',
  'schema': {'properties': {'requests': {'description': 'Component search requests. Use one '
                                                        'request per distinct power rail or '
                                                        'component category.\n',
                                         'items': {'properties': {'ambient_temp_c': {'default': 30,
                                                                                     'description': 'Maximum '
                                                                                                    'ambient '
                                                                                                    'temperature '
                                                                                                    'in '
                                                                                                    'degrees '
                                                                                                    'Celsius.',
                                                                                     'type': 'number'},
                                                                  'category': {'description': 'Component '
                                                                                              'category. '
                                                                                              'Currently '
                                                                                              'only '
                                                                                              'power_converters '
                                                                                              'is '
                                                                                              'supported.',
                                                                               'enum': ['power_converters'],
                                                                               'type': 'string'},
                                                                  'id': {'description': 'Optional '
                                                                                        'caller-supplied '
                                                                                        'ID for '
                                                                                        'correlating '
                                                                                        'responses.'},
                                                                  'input_voltage_max': {'description': 'Maximum '
                                                                                                       'input '
                                                                                                       'voltage '
                                                                                                       'in '
                                                                                                       'volts. '
                                                                                                       'For '
                                                                                                       'fixed '
                                                                                                       'input '
                                                                                                       'voltage, '
                                                                                                       'use '
                                                                                                       'the '
                                                                                                       'same '
                                                                                                       'value '
                                                                                                       'as '
                                                                                                       'input_voltage_min.',
                                                                                        'type': 'number'},
                                                                  'input_voltage_min': {'description': 'Minimum '
                                                                                                       'input '
                                                                                                       'voltage '
                                                                                                       'in '
                                                                                                       'volts. '
                                                                                                       'For '
                                                                                                       'fixed '
                                                                                                       'input '
                                                                                                       'voltage, '
                                                                                                       'use '
                                                                                                       'the '
                                                                                                       'same '
                                                                                                       'value '
                                                                                                       'as '
                                                                                                       'input_voltage_max.',
                                                                                        'type': 'number'},
                                                                  'isolated': {'default': False,
                                                                               'description': 'Whether '
                                                                                              'the '
                                                                                              'design '
                                                                                              'should '
                                                                                              'be '
                                                                                              'isolated.',
                                                                               'type': 'boolean'},
                                                                  'max_results': {'default': 10,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'candidate '
                                                                                                 'components '
                                                                                                 'to '
                                                                                                 'return.',
                                                                                  'type': 'integer'},
                                                                  'optimization': {'default': 'balanced',
                                                                                   'description': 'Optimization '
                                                                                                  'goal '
                                                                                                  'for '
                                                                                                  'WEBENCH '
                                                                                                  'ranking.',
                                                                                   'enum': ['balanced',
                                                                                            'low_cost',
                                                                                            'high_efficiency',
                                                                                            'small_footprint'],
                                                                                   'type': 'string'},
                                                                  'output_current_max': {'description': 'Maximum '
                                                                                                        'output '
                                                                                                        'current '
                                                                                                        'in '
                                                                                                        'amps.',
                                                                                         'type': 'number'},
                                                                  'output_voltage': {'description': 'Target '
                                                                                                    'output '
                                                                                                    'voltage '
                                                                                                    'in '
                                                                                                    'volts.',
                                                                                     'type': 'number'},
                                                                  'supply_type': {'default': 'dc',
                                                                                  'description': 'dc '
                                                                                                 'for '
                                                                                                 'DC/DC '
                                                                                                 'converters, '
                                                                                                 'ac '
                                                                                                 'for '
                                                                                                 'AC/DC '
                                                                                                 'converters.',
                                                                                  'enum': ['dc',
                                                                                           'ac'],
                                                                                  'type': 'string'}},
                                                   'required': ['category',
                                                                'input_voltage_min',
                                                                'input_voltage_max',
                                                                'output_voltage',
                                                                'output_current_max'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_components',
  'skill_method_py': 'search_components',
  'skill_method_ts': 'searchComponents'},
 {'app_id': 'events',
  'app_namespace_py': 'events',
  'app_namespace_ts': 'events',
  'description': 'Search for local or online events, meetups, hackathons, conferences, workshops, '
                 'networking events, parties, concerts, or any community gathering. Use ONLY this '
                 'skill for event searches — do NOT additionally call web.search or any other '
                 'search skill for the same query. Sources: Meetup, Luma, Eventbrite, Google '
                 'Events, Resident Advisor (electronic music/clubs), Siegessäule (Berlin LGBTQ+ '
                 'events), Berlin Philharmonic (classical concerts in Berlin), and official event '
                 'schedules for GPN24, 39C3, 38C3',
  'description_key': 'events.search.description',
  'schema': {'properties': {'provider': {'description': "The event provider to use. 'auto' "
                                                        '(default) queries all providers in '
                                                        'parallel for best coverage. Use specific '
                                                        'providers when the user asks about a '
                                                        "particular platform/type: 'Eventbrite' "
                                                        "for Eventbrite-only results, 'Resident "
                                                        "Advisor' for electronic music/clubs, "
                                                        "'Siegessäule' for Berlin LGBTQ+ events, "
                                                        "'GPN24', '39C3', '38C3', or '37C3' for "
                                                        'official schedules of those events.\n',
                                         'enum': ['auto',
                                                  'Meetup',
                                                  'Luma',
                                                  'Eventbrite',
                                                  'Google Events',
                                                  'Resident Advisor',
                                                  'Siegessäule',
                                                  'Berlin Philharmonic',
                                                  'GPN24',
                                                  '39C3',
                                                  '38C3',
                                                  '37C3'],
                                         'type': 'string'},
                            'requests': {'description': 'REQUIRED: Array of event search request '
                                                        'objects for parallel processing.\n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single search.\n'
                                                        'Example for single search: {"requests": '
                                                        '[{"query": "AI", "location": "Berlin, '
                                                        'Germany"}]}\n'
                                                        'Example for multiple searches: '
                                                        '{"requests": [{"query": "AI", "location": '
                                                        '"Berlin"}, {"query": "Python", '
                                                        '"location": "Munich"}]}\n'
                                                        "Each object must contain 'query' and "
                                                        "either 'location' (or lat/lon) for city "
                                                        'searches,\n'
                                                        "or 'conference' for GPN/Congress schedule "
                                                        'searches. All other parameters are '
                                                        'optional.\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        'not provided.\n',
                                         'items': {'properties': {'concert_tags': {'description': 'Optional '
                                                                                                  'tag '
                                                                                                  'filters '
                                                                                                  'for '
                                                                                                  'the '
                                                                                                  'Berlin '
                                                                                                  'Philharmonic '
                                                                                                  'provider. '
                                                                                                  'Use '
                                                                                                  'when '
                                                                                                  'the '
                                                                                                  'user '
                                                                                                  'asks '
                                                                                                  'about '
                                                                                                  'classical '
                                                                                                  'concerts '
                                                                                                  'in '
                                                                                                  'Berlin. '
                                                                                                  'Known '
                                                                                                  'values: '
                                                                                                  'Piano, '
                                                                                                  'Chamber '
                                                                                                  'Music, '
                                                                                                  'Jazz, '
                                                                                                  'Organ, '
                                                                                                  'Modern, '
                                                                                                  'Lunch '
                                                                                                  'Concerts, '
                                                                                                  'Singers, '
                                                                                                  'Children '
                                                                                                  'and '
                                                                                                  'Family, '
                                                                                                  'World. '
                                                                                                  'Ignored '
                                                                                                  'by '
                                                                                                  'all '
                                                                                                  'other '
                                                                                                  'providers.\n',
                                                                                   'items': {'type': 'string'},
                                                                                   'type': 'array'},
                                                                  'conference': {'description': 'Known '
                                                                                                'GPN/Congress '
                                                                                                'schedule '
                                                                                                'to '
                                                                                                'search. '
                                                                                                'Supported '
                                                                                                'values: '
                                                                                                'GPN24, '
                                                                                                '39C3, '
                                                                                                '38C3, '
                                                                                                '37C3.',
                                                                                 'enum': ['GPN24',
                                                                                          '39C3',
                                                                                          '38C3',
                                                                                          '37C3'],
                                                                                 'type': 'string'},
                                                                  'count': {'default': 10,
                                                                            'description': 'Maximum '
                                                                                           'number '
                                                                                           'of '
                                                                                           'events '
                                                                                           'to '
                                                                                           'return '
                                                                                           '(default: '
                                                                                           '10, '
                                                                                           'max: '
                                                                                           '50). '
                                                                                           'Use 10 '
                                                                                           'unless '
                                                                                           'the '
                                                                                           'user '
                                                                                           'asks '
                                                                                           'for '
                                                                                           'more '
                                                                                           'results.',
                                                                            'maximum': 50,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'end_date': {'description': 'End '
                                                                                              'of '
                                                                                              'date '
                                                                                              'range '
                                                                                              'in '
                                                                                              'ISO '
                                                                                              '8601 '
                                                                                              'format '
                                                                                              '(same '
                                                                                              'format '
                                                                                              'as '
                                                                                              'start_date). '
                                                                                              'If '
                                                                                              'omitted, '
                                                                                              'no '
                                                                                              'upper '
                                                                                              'bound '
                                                                                              'is '
                                                                                              'applied.',
                                                                               'type': 'string'},
                                                                  'event_type': {'description': 'Filter '
                                                                                                'by '
                                                                                                'event '
                                                                                                'type. '
                                                                                                'Use '
                                                                                                "'PHYSICAL' "
                                                                                                'when '
                                                                                                'user '
                                                                                                'searches '
                                                                                                'for '
                                                                                                'events '
                                                                                                'in '
                                                                                                'a '
                                                                                                'city '
                                                                                                '(default '
                                                                                                'for '
                                                                                                'location-based '
                                                                                                'searches). '
                                                                                                'Use '
                                                                                                "'ONLINE' "
                                                                                                'when '
                                                                                                'user '
                                                                                                'explicitly '
                                                                                                'asks '
                                                                                                'for '
                                                                                                'virtual/online/remote '
                                                                                                'events. '
                                                                                                'Omit '
                                                                                                'only '
                                                                                                'when '
                                                                                                'user '
                                                                                                'wants '
                                                                                                'both '
                                                                                                'types.',
                                                                                 'enum': ['PHYSICAL',
                                                                                          'ONLINE'],
                                                                                 'type': 'string'},
                                                                  'lat': {'description': 'Latitude '
                                                                                         'of '
                                                                                         'search '
                                                                                         'center '
                                                                                         '(decimal '
                                                                                         'degrees). '
                                                                                         'Overrides '
                                                                                         'location '
                                                                                         'string '
                                                                                         'if '
                                                                                         'provided.',
                                                                          'type': 'number'},
                                                                  'location': {'description': 'City '
                                                                                              'name '
                                                                                              'or '
                                                                                              "'city, "
                                                                                              "country' "
                                                                                              'string '
                                                                                              '(e.g. '
                                                                                              "'Berlin, "
                                                                                              "Germany', "
                                                                                              "'New "
                                                                                              "York', "
                                                                                              "'Paris'). "
                                                                                              'Used '
                                                                                              'if '
                                                                                              'lat/lon '
                                                                                              'are '
                                                                                              'not '
                                                                                              'provided. '
                                                                                              'Not '
                                                                                              'required '
                                                                                              'when '
                                                                                              'using '
                                                                                              'a '
                                                                                              'GPN/Congress '
                                                                                              'event '
                                                                                              'schedule '
                                                                                              'provider '
                                                                                              'with '
                                                                                              'a '
                                                                                              'conference '
                                                                                              'value.',
                                                                               'type': 'string'},
                                                                  'lon': {'description': 'Longitude '
                                                                                         'of '
                                                                                         'search '
                                                                                         'center '
                                                                                         '(decimal '
                                                                                         'degrees). '
                                                                                         'Overrides '
                                                                                         'location '
                                                                                         'string '
                                                                                         'if '
                                                                                         'provided.',
                                                                          'type': 'number'},
                                                                  'past_events': {'default': False,
                                                                                  'description': 'Default '
                                                                                                 'false. '
                                                                                                 'Set '
                                                                                                 'true '
                                                                                                 'only '
                                                                                                 'when '
                                                                                                 'the '
                                                                                                 'user '
                                                                                                 'explicitly '
                                                                                                 'asks '
                                                                                                 'to '
                                                                                                 'include '
                                                                                                 'past/completed '
                                                                                                 'conference '
                                                                                                 'sessions.',
                                                                                  'type': 'boolean'},
                                                                  'provider': {'description': 'Provider '
                                                                                              'for '
                                                                                              'this '
                                                                                              'request. '
                                                                                              'Overrides '
                                                                                              'the '
                                                                                              'top-level '
                                                                                              'provider '
                                                                                              'when '
                                                                                              'set.',
                                                                               'enum': ['auto',
                                                                                        'Meetup',
                                                                                        'Luma',
                                                                                        'Eventbrite',
                                                                                        'Google '
                                                                                        'Events',
                                                                                        'Resident '
                                                                                        'Advisor',
                                                                                        'Siegessäule',
                                                                                        'Berlin '
                                                                                        'Philharmonic',
                                                                                        'GPN24',
                                                                                        '39C3',
                                                                                        '38C3',
                                                                                        '37C3'],
                                                                               'type': 'string'},
                                                                  'providers': {'description': 'Specific '
                                                                                               'providers '
                                                                                               'for '
                                                                                               'this '
                                                                                               'request. '
                                                                                               'Use '
                                                                                               'only '
                                                                                               'when '
                                                                                               'the '
                                                                                               'user '
                                                                                               'asks '
                                                                                               'to '
                                                                                               'search '
                                                                                               'multiple '
                                                                                               'named '
                                                                                               'event '
                                                                                               'platforms.',
                                                                                'items': {'enum': ['Meetup',
                                                                                                   'Luma',
                                                                                                   'Eventbrite',
                                                                                                   'Google '
                                                                                                   'Events',
                                                                                                   'Resident '
                                                                                                   'Advisor',
                                                                                                   'Siegessäule',
                                                                                                   'Berlin '
                                                                                                   'Philharmonic',
                                                                                                   'GPN24',
                                                                                                   '39C3',
                                                                                                   '38C3',
                                                                                                   '37C3'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                                  'query': {'description': 'Topic '
                                                                                           'or '
                                                                                           'theme '
                                                                                           'of '
                                                                                           'events '
                                                                                           'to '
                                                                                           'search '
                                                                                           'for '
                                                                                           '(e.g. '
                                                                                           "'AI', "
                                                                                           "'Python', "
                                                                                           "'hackathon', "
                                                                                           "'startup', "
                                                                                           "'networking'). "
                                                                                           'Do NOT '
                                                                                           'include '
                                                                                           'platform '
                                                                                           'or app '
                                                                                           'names '
                                                                                           'such '
                                                                                           'as '
                                                                                           "'meetup', "
                                                                                           "'luma', "
                                                                                           'or '
                                                                                           "'eventbrite' "
                                                                                           '— '
                                                                                           'these '
                                                                                           'are '
                                                                                           'stripped '
                                                                                           'automatically '
                                                                                           'and '
                                                                                           'reduce '
                                                                                           'result '
                                                                                           'quality.\n',
                                                                            'type': 'string'},
                                                                  'radius_miles': {'default': 25,
                                                                                   'description': 'Search '
                                                                                                  'radius '
                                                                                                  'in '
                                                                                                  'miles '
                                                                                                  'from '
                                                                                                  'the '
                                                                                                  'center '
                                                                                                  'coordinates '
                                                                                                  '(default: '
                                                                                                  '25, '
                                                                                                  '~40 '
                                                                                                  'km). '
                                                                                                  'Only '
                                                                                                  'applies '
                                                                                                  'to '
                                                                                                  'PHYSICAL '
                                                                                                  'events.',
                                                                                   'type': 'number'},
                                                                  'start_date': {'description': 'Start '
                                                                                                'of '
                                                                                                'date '
                                                                                                'range '
                                                                                                'in '
                                                                                                'ISO '
                                                                                                '8601 '
                                                                                                'format. '
                                                                                                'Include '
                                                                                                'timezone '
                                                                                                'if '
                                                                                                'known '
                                                                                                '(e.g. '
                                                                                                "'2026-03-01T00:00:00+01:00[Europe/Berlin]'). "
                                                                                                'If '
                                                                                                'omitted, '
                                                                                                'defaults '
                                                                                                'to '
                                                                                                'now.',
                                                                                 'type': 'string'}},
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'fitness',
  'app_namespace_py': 'fitness',
  'app_namespace_ts': 'fitness',
  'description': 'Search Urban Sports Club public fitness locations. Use this when the user asks '
                 'for gyms, studios, pools, or Urban Sports locations near a city, address, or '
                 'radius. Do not use it for class availability; use fitness.search_classes for '
                 'dated class searches.',
  'description_key': 'fitness.search_locations.description',
  'schema': {'properties': {'requests': {'description': 'Location search requests.',
                                         'items': {'properties': {'address': {'type': 'string'},
                                                                  'category': {'type': 'string'},
                                                                  'city': {'type': 'string'},
                                                                  'lat': {'type': 'number'},
                                                                  'limit': {'type': 'number'},
                                                                  'lon': {'type': 'number'},
                                                                  'plan': {'type': 'string'},
                                                                  'query': {'type': 'string'},
                                                                  'radius_km': {'type': 'number'}},
                                                   'type': 'object'},
                                         'type': 'array'}},
             'type': 'object'},
  'skill_id': 'search_locations',
  'skill_method_py': 'search_locations',
  'skill_method_ts': 'searchLocations'},
 {'app_id': 'fitness',
  'app_namespace_py': 'fitness',
  'app_namespace_ts': 'fitness',
  'description': 'Search available Urban Sports Club public fitness classes. Use this when the '
                 'user asks for dated fitness classes, course availability, free spots, on-site '
                 'classes, online classes, or plan-filtered Urban Sports classes. Omit plan unless '
                 'the user explicitly asks for Essential, Classic, Premium, or Max.',
  'description_key': 'fitness.search_classes.description',
  'schema': {'properties': {'requests': {'description': 'Class search requests.',
                                         'items': {'properties': {'address': {'type': 'string'},
                                                                  'attendance_mode': {'type': 'string'},
                                                                  'category': {'type': 'string'},
                                                                  'city': {'type': 'string'},
                                                                  'days': {'type': 'number'},
                                                                  'end_date': {'type': 'string'},
                                                                  'lat': {'type': 'number'},
                                                                  'limit': {'type': 'number'},
                                                                  'lon': {'type': 'number'},
                                                                  'min_spots': {'type': 'number'},
                                                                  'plan': {'type': 'string'},
                                                                  'query': {'type': 'string'},
                                                                  'radius_km': {'type': 'number'},
                                                                  'start_date': {'type': 'string'},
                                                                  'venue_id': {'type': 'string'}},
                                                   'type': 'object'},
                                         'type': 'array'}},
             'type': 'object'},
  'skill_id': 'search_classes',
  'skill_method_py': 'search_classes',
  'skill_method_ts': 'searchClasses'},
 {'app_id': 'health',
  'app_namespace_py': 'health',
  'app_namespace_ts': 'health',
  'description': 'Search available medical appointments at German doctors/specialists by '
                 'speciality and city. Covers any medical booking — general practitioners, '
                 'specialists (e.g. dentist, dermatologist, gynecologist), scans and imaging (e.g. '
                 'MRT/MRI, CT, Röntgen, Ultraschall), vaccinations, check-ups, blood tests, and '
                 'other examinations. Note: "Termin" in a medical context means appointment, not '
                 'event — route here instead of events-search. Sources: Doctolib, Jameda (Germany '
                 'only).',
  'description_key': 'app_skills.health.search_appointments.description',
  'schema': {'properties': {'requests': {'description': 'Array of appointment search requests. '
                                                        'Each request searches for available '
                                                        'doctor appointments for a given '
                                                        'speciality and city.\n',
                                         'items': {'properties': {'city': {'description': 'City '
                                                                                          'where '
                                                                                          'to '
                                                                                          'search '
                                                                                          'for '
                                                                                          'appointments. '
                                                                                          'Supports '
                                                                                          'German '
                                                                                          'and '
                                                                                          'English '
                                                                                          'city '
                                                                                          'names. '
                                                                                          'Examples: '
                                                                                          '"Berlin", '
                                                                                          '"München", '
                                                                                          '"Munich", '
                                                                                          '"Hamburg", '
                                                                                          '"Köln", '
                                                                                          '"Frankfurt", '
                                                                                          '"Stuttgart", '
                                                                                          '"Düsseldorf", '
                                                                                          '"Dresden", '
                                                                                          '"Leipzig", '
                                                                                          '"Hannover", '
                                                                                          '"Nürnberg", '
                                                                                          '"Bonn", '
                                                                                          '"Heidelberg".\n',
                                                                           'type': 'string'},
                                                                  'days_ahead': {'default': 7,
                                                                                 'description': 'How '
                                                                                                'many '
                                                                                                'days '
                                                                                                'ahead '
                                                                                                'to '
                                                                                                'search '
                                                                                                'for '
                                                                                                'appointments. '
                                                                                                'Must '
                                                                                                'be '
                                                                                                'one '
                                                                                                'of '
                                                                                                '1, '
                                                                                                '3, '
                                                                                                'or '
                                                                                                '7 '
                                                                                                '(Doctolib '
                                                                                                'API '
                                                                                                'caps '
                                                                                                'availability '
                                                                                                'queries '
                                                                                                'at '
                                                                                                '7 '
                                                                                                'days). '
                                                                                                'Defaults '
                                                                                                'to '
                                                                                                '7.\n',
                                                                                 'enum': [1, 3, 7],
                                                                                 'type': 'integer'},
                                                                  'insurance_sector': {'description': 'Insurance '
                                                                                                      'type '
                                                                                                      'filter. '
                                                                                                      '"public" '
                                                                                                      'for '
                                                                                                      'gesetzliche '
                                                                                                      'Krankenversicherung '
                                                                                                      '(GKV), '
                                                                                                      '"private" '
                                                                                                      'for '
                                                                                                      'private '
                                                                                                      'Krankenversicherung '
                                                                                                      '(PKV). '
                                                                                                      'Omit '
                                                                                                      'to '
                                                                                                      'show '
                                                                                                      'results '
                                                                                                      'for '
                                                                                                      'all '
                                                                                                      'insurance '
                                                                                                      'types.\n',
                                                                                       'enum': ['public',
                                                                                                'private'],
                                                                                       'type': 'string'},
                                                                  'language': {'description': 'Filter '
                                                                                              'for '
                                                                                              'doctors '
                                                                                              'who '
                                                                                              'speak '
                                                                                              'a '
                                                                                              'specific '
                                                                                              'language. '
                                                                                              'Language '
                                                                                              'codes: '
                                                                                              '"de" '
                                                                                              '(German), '
                                                                                              '"gb" '
                                                                                              '(English), '
                                                                                              '"ru" '
                                                                                              '(Russian), '
                                                                                              '"tr" '
                                                                                              '(Turkish), '
                                                                                              '"ar" '
                                                                                              '(Arabic), '
                                                                                              '"fr" '
                                                                                              '(French), '
                                                                                              '"es" '
                                                                                              '(Spanish), '
                                                                                              '"it" '
                                                                                              '(Italian), '
                                                                                              '"pl" '
                                                                                              '(Polish), '
                                                                                              '"ro" '
                                                                                              '(Romanian), '
                                                                                              '"zh" '
                                                                                              '(Chinese).\n',
                                                                               'type': 'string'},
                                                                  'max_doctors': {'default': 10,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'doctors '
                                                                                                 'to '
                                                                                                 'check '
                                                                                                 'for '
                                                                                                 'availability. '
                                                                                                 'Higher '
                                                                                                 'values '
                                                                                                 'return '
                                                                                                 'more '
                                                                                                 'results '
                                                                                                 'but '
                                                                                                 'take '
                                                                                                 'longer. '
                                                                                                 'Defaults '
                                                                                                 'to '
                                                                                                 '10.\n',
                                                                                  'type': 'integer'},
                                                                  'provider_platform': {'default': 'both',
                                                                                        'description': 'Booking '
                                                                                                       'platform '
                                                                                                       'to '
                                                                                                       'search. '
                                                                                                       '"both" '
                                                                                                       '(default) '
                                                                                                       'searches '
                                                                                                       'Doctolib '
                                                                                                       'and '
                                                                                                       'Jameda '
                                                                                                       'in '
                                                                                                       'parallel '
                                                                                                       'and '
                                                                                                       'merges '
                                                                                                       'results '
                                                                                                       'sorted '
                                                                                                       'by '
                                                                                                       'soonest '
                                                                                                       'slot. '
                                                                                                       '"doctolib_de" '
                                                                                                       'for '
                                                                                                       'Doctolib '
                                                                                                       'Germany '
                                                                                                       'only. '
                                                                                                       '"jameda" '
                                                                                                       'for '
                                                                                                       'Jameda '
                                                                                                       'Germany '
                                                                                                       'only '
                                                                                                       '(includes '
                                                                                                       'ratings, '
                                                                                                       'prices, '
                                                                                                       'direct '
                                                                                                       'booking '
                                                                                                       'URLs).\n',
                                                                                        'enum': ['both',
                                                                                                 'doctolib_de',
                                                                                                 'jameda'],
                                                                                        'type': 'string'},
                                                                  'speciality': {'description': 'Doctor '
                                                                                                'speciality '
                                                                                                'or '
                                                                                                'type. '
                                                                                                'Supports '
                                                                                                'German '
                                                                                                'and '
                                                                                                'English '
                                                                                                'names. '
                                                                                                'Examples: '
                                                                                                '"augenarzt", '
                                                                                                '"hautarzt", '
                                                                                                '"allgemeinmedizin", '
                                                                                                '"zahnarzt", '
                                                                                                '"gynäkologie", '
                                                                                                '"kardiologie", '
                                                                                                '"orthopädie", '
                                                                                                '"neurologie", '
                                                                                                '"kinderarzt", '
                                                                                                '"hno", '
                                                                                                '"physiotherapie", '
                                                                                                '"urologie", '
                                                                                                '"ophthalmologist", '
                                                                                                '"dermatologist", '
                                                                                                '"general_practitioner", '
                                                                                                '"dentist", '
                                                                                                '"cardiologist", '
                                                                                                '"neurologist", '
                                                                                                '"pediatrician".\n',
                                                                                 'type': 'string'},
                                                                  'telehealth': {'default': False,
                                                                                 'description': 'If '
                                                                                                'true, '
                                                                                                'only '
                                                                                                'return '
                                                                                                'doctors '
                                                                                                'offering '
                                                                                                'telehealth '
                                                                                                '(video '
                                                                                                'consultation) '
                                                                                                'appointments. '
                                                                                                'Defaults '
                                                                                                'to '
                                                                                                'false.\n',
                                                                                 'type': 'boolean'},
                                                                  'visit_motive_category': {'description': 'Filter '
                                                                                                           'results '
                                                                                                           'by '
                                                                                                           'appointment '
                                                                                                           'type '
                                                                                                           'category. '
                                                                                                           'When '
                                                                                                           'set, '
                                                                                                           'the '
                                                                                                           'skill '
                                                                                                           'searches '
                                                                                                           'a '
                                                                                                           'larger '
                                                                                                           'pool '
                                                                                                           'of '
                                                                                                           'doctors '
                                                                                                           'and '
                                                                                                           'filters '
                                                                                                           'by '
                                                                                                           'the '
                                                                                                           'Doctolib '
                                                                                                           'visit '
                                                                                                           'motive '
                                                                                                           'name '
                                                                                                           'to '
                                                                                                           'return '
                                                                                                           'only '
                                                                                                           'relevant '
                                                                                                           'appointment '
                                                                                                           'types. '
                                                                                                           '"general" '
                                                                                                           '= '
                                                                                                           'consultation, '
                                                                                                           'acute '
                                                                                                           'visit, '
                                                                                                           'new '
                                                                                                           'patient '
                                                                                                           'examination. '
                                                                                                           '"checkup" '
                                                                                                           '= '
                                                                                                           'preventive '
                                                                                                           'screening, '
                                                                                                           'health '
                                                                                                           'check, '
                                                                                                           'cancer '
                                                                                                           'screening. '
                                                                                                           '"vaccination" '
                                                                                                           '= '
                                                                                                           'immunisation '
                                                                                                           'appointments. '
                                                                                                           '"followup" '
                                                                                                           '= '
                                                                                                           'follow-up '
                                                                                                           'visit, '
                                                                                                           'existing '
                                                                                                           'patient, '
                                                                                                           'check-up '
                                                                                                           'after '
                                                                                                           'treatment.\n',
                                                                                            'enum': ['general',
                                                                                                     'checkup',
                                                                                                     'vaccination',
                                                                                                     'followup'],
                                                                                            'type': 'string'}},
                                                   'required': ['speciality', 'city'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_appointments',
  'skill_method_py': 'search_appointments',
  'skill_method_ts': 'searchAppointments'},
 {'app_id': 'health',
  'app_namespace_py': 'health',
  'app_namespace_ts': 'health',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'health.create_report.description',
  'schema': {'properties': {}, 'type': 'object'},
  'skill_id': 'create_report',
  'skill_method_py': 'create_report',
  'skill_method_ts': 'createReport'},
 {'app_id': 'home',
  'app_namespace_py': 'home',
  'app_namespace_ts': 'home',
  'description': 'Search for apartments, houses, and WG rooms in German cities. Searches '
                 'ImmoScout24, Kleinanzeigen, and WG-Gesucht simultaneously. Returns listings with '
                 'prices, sizes, rooms, addresses, and direct links. Costs 10 credits per search. '
                 'Use when user asks about finding housing in Germany.',
  'description_key': 'app_skills.home.search.description',
  'schema': {'properties': {'requests': {'description': 'Array of housing search requests. Each '
                                                        'request searches for apartments and rooms '
                                                        'in a German city across multiple '
                                                        'platforms.\n',
                                         'items': {'properties': {'listing_type': {'default': 'rent',
                                                                                   'description': 'Type '
                                                                                                  'of '
                                                                                                  'listing. '
                                                                                                  '"rent" '
                                                                                                  'for '
                                                                                                  'rentals '
                                                                                                  '(default), '
                                                                                                  '"buy" '
                                                                                                  'for '
                                                                                                  'purchases. '
                                                                                                  'Note: '
                                                                                                  'WG-Gesucht '
                                                                                                  'only '
                                                                                                  'has '
                                                                                                  'rentals '
                                                                                                  'and '
                                                                                                  'is '
                                                                                                  'skipped '
                                                                                                  'for '
                                                                                                  '"buy".\n',
                                                                                   'enum': ['rent',
                                                                                            'buy'],
                                                                                   'type': 'string'},
                                                                  'max_results': {'default': 10,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'listings '
                                                                                                 'to '
                                                                                                 'return '
                                                                                                 '(1-20, '
                                                                                                 'default '
                                                                                                 '10).',
                                                                                  'maximum': 20,
                                                                                  'minimum': 1,
                                                                                  'type': 'integer'},
                                                                  'providers': {'description': 'Optional '
                                                                                               'list '
                                                                                               'of '
                                                                                               'providers '
                                                                                               'to '
                                                                                               'search. '
                                                                                               'Defaults '
                                                                                               'to '
                                                                                               'all '
                                                                                               'three.\n',
                                                                                'items': {'enum': ['ImmoScout24',
                                                                                                   'Kleinanzeigen',
                                                                                                   'WG-Gesucht'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                                  'query': {'description': 'City '
                                                                                           'or '
                                                                                           'location '
                                                                                           'name '
                                                                                           'to '
                                                                                           'search '
                                                                                           'in, '
                                                                                           'e.g. '
                                                                                           '"Berlin", '
                                                                                           '"Munich", '
                                                                                           '"Hamburg".\n',
                                                                            'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'images',
  'app_namespace_py': 'images',
  'app_namespace_ts': 'images',
  'description': 'Generate high-quality images from text prompts and/or reference images '
                 '(image-to-image editing). Also use for: mockups, design concepts, visual mockup '
                 'creation, logo mockups, product mockups, illustration requests, visual design, '
                 'concept art, posters, banners, thumbnails, or any request that implies creating '
                 'a visual output. Use output_filetype="svg" for logos, icons, illustrations, and '
                 'any other vector graphics that need to be scalable or editable. When the user '
                 'provides uploaded images as refe',
  'description_key': 'images.generate.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of image generation '
                                                        'request objects for parallel processing '
                                                        '(up to 5 requests).\n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single image.\n'
                                                        'Example for single image: {"requests": '
                                                        '[{"prompt": "a cute cat"}]}\n'
                                                        "Each object must contain 'prompt' "
                                                        '(detailed description), and can include '
                                                        'optional\n'
                                                        "'aspect_ratio', 'output_filetype', and "
                                                        "'quality'.\n",
                                         'items': {'properties': {'aspect_ratio': {'default': '1:1',
                                                                                   'description': 'Aspect '
                                                                                                  'ratio '
                                                                                                  'of '
                                                                                                  'the '
                                                                                                  'generated '
                                                                                                  'image',
                                                                                   'enum': ['1:1',
                                                                                            '16:9',
                                                                                            '4:3',
                                                                                            '3:2',
                                                                                            '2:3',
                                                                                            '9:16'],
                                                                                   'type': 'string'},
                                                                  'output_filetype': {'default': 'png',
                                                                                      'description': 'Output '
                                                                                                     'file '
                                                                                                     'format. '
                                                                                                     'Use '
                                                                                                     '"svg" '
                                                                                                     'to '
                                                                                                     'generate '
                                                                                                     'a '
                                                                                                     'scalable '
                                                                                                     'vector '
                                                                                                     'graphic '
                                                                                                     '(SVG) '
                                                                                                     'via\n'
                                                                                                     'Recraft '
                                                                                                     'V4.1 '
                                                                                                     '— '
                                                                                                     'ideal '
                                                                                                     'for '
                                                                                                     'logos, '
                                                                                                     'icons, '
                                                                                                     'illustrations, '
                                                                                                     'and '
                                                                                                     'any '
                                                                                                     'graphic '
                                                                                                     'that '
                                                                                                     'needs\n'
                                                                                                     'to '
                                                                                                     'be '
                                                                                                     'scalable, '
                                                                                                     'editable '
                                                                                                     'in '
                                                                                                     'design '
                                                                                                     'tools, '
                                                                                                     'or '
                                                                                                     'used '
                                                                                                     'at '
                                                                                                     'any '
                                                                                                     'size '
                                                                                                     'without '
                                                                                                     'quality '
                                                                                                     'loss.\n'
                                                                                                     'Use '
                                                                                                     '"png" '
                                                                                                     'or '
                                                                                                     '"jpg" '
                                                                                                     'for '
                                                                                                     'photos, '
                                                                                                     'realistic '
                                                                                                     'scenes, '
                                                                                                     'and '
                                                                                                     'detailed '
                                                                                                     'raster '
                                                                                                     'images.\n'
                                                                                                     'When '
                                                                                                     'a '
                                                                                                     'Recraft '
                                                                                                     'model '
                                                                                                     'is '
                                                                                                     'selected, '
                                                                                                     'Recraft '
                                                                                                     'V4 '
                                                                                                     'is '
                                                                                                     'used '
                                                                                                     'for '
                                                                                                     'raster '
                                                                                                     'output '
                                                                                                     'as '
                                                                                                     'well.\n',
                                                                                      'enum': ['png',
                                                                                               'jpg',
                                                                                               'svg'],
                                                                                      'type': 'string'},
                                                                  'prompt': {'description': 'Detailed '
                                                                                            'description '
                                                                                            'of '
                                                                                            'the '
                                                                                            'image '
                                                                                            'to '
                                                                                            'generate',
                                                                             'type': 'string'},
                                                                  'quality': {'default': 'default',
                                                                              'description': 'Generation '
                                                                                             'quality. '
                                                                                             'Controls '
                                                                                             'which '
                                                                                             'model '
                                                                                             'tier '
                                                                                             'is '
                                                                                             'used '
                                                                                             'when '
                                                                                             'Recraft '
                                                                                             'is '
                                                                                             'the '
                                                                                             'provider.\n'
                                                                                             'For '
                                                                                             'SVG '
                                                                                             'output '
                                                                                             '(output_filetype="svg"):\n'
                                                                                             '  '
                                                                                             '"default" '
                                                                                             'uses '
                                                                                             'Recraft '
                                                                                             'V4.1 '
                                                                                             'Vector '
                                                                                             '(100 '
                                                                                             'credits '
                                                                                             '— '
                                                                                             'good '
                                                                                             'for '
                                                                                             'web/UI '
                                                                                             'use).\n'
                                                                                             '  '
                                                                                             '"max" '
                                                                                             'uses '
                                                                                             'Recraft '
                                                                                             'V4.1 '
                                                                                             'Pro '
                                                                                             'Vector '
                                                                                             '(300 '
                                                                                             'credits '
                                                                                             '— '
                                                                                             'best '
                                                                                             'for '
                                                                                             'print, '
                                                                                             'large-format,\n'
                                                                                             '  or '
                                                                                             'highly '
                                                                                             'detailed '
                                                                                             'vector '
                                                                                             'illustrations).\n'
                                                                                             'For '
                                                                                             'raster '
                                                                                             'output '
                                                                                             '(output_filetype="png"/"jpg") '
                                                                                             'with '
                                                                                             'a '
                                                                                             'Recraft '
                                                                                             'model '
                                                                                             'selected:\n'
                                                                                             '  '
                                                                                             '"default" '
                                                                                             'uses '
                                                                                             'Recraft '
                                                                                             'V4.1 '
                                                                                             '(50 '
                                                                                             'credits '
                                                                                             '— '
                                                                                             'fast, '
                                                                                             'cost-effective).\n'
                                                                                             '  '
                                                                                             '"max" '
                                                                                             'uses '
                                                                                             'Recraft '
                                                                                             'V4.1 '
                                                                                             'Pro '
                                                                                             '(250 '
                                                                                             'credits '
                                                                                             '— '
                                                                                             'high-resolution, '
                                                                                             'print-ready).\n'
                                                                                             'For '
                                                                                             'other '
                                                                                             'raster '
                                                                                             'models '
                                                                                             '(Google '
                                                                                             'Gemini, '
                                                                                             'GPT '
                                                                                             'Image '
                                                                                             '2, '
                                                                                             'FLUX), '
                                                                                             'quality '
                                                                                             'may '
                                                                                             'be '
                                                                                             'handled '
                                                                                             'by '
                                                                                             'the '
                                                                                             'provider.\n',
                                                                              'enum': ['default',
                                                                                       'max'],
                                                                              'type': 'string'},
                                                                  'reference_images': {'description': 'Optional '
                                                                                                      'list '
                                                                                                      'of '
                                                                                                      'reference '
                                                                                                      'image '
                                                                                                      'filenames '
                                                                                                      '(embed_refs) '
                                                                                                      'to '
                                                                                                      'use '
                                                                                                      'as '
                                                                                                      'visual\n'
                                                                                                      'references '
                                                                                                      'for '
                                                                                                      'this '
                                                                                                      'generation. '
                                                                                                      'Pass '
                                                                                                      'the '
                                                                                                      'exact '
                                                                                                      'embed_ref '
                                                                                                      'values '
                                                                                                      '(original\n'
                                                                                                      'filenames, '
                                                                                                      'e.g. '
                                                                                                      '"my_photo.jpg") '
                                                                                                      'from '
                                                                                                      'the '
                                                                                                      'toon '
                                                                                                      'blocks '
                                                                                                      'in '
                                                                                                      'the '
                                                                                                      'conversation.\n'
                                                                                                      'The '
                                                                                                      'server '
                                                                                                      'resolves '
                                                                                                      'all '
                                                                                                      'cryptographic '
                                                                                                      'and '
                                                                                                      'storage '
                                                                                                      'details '
                                                                                                      'automatically.\n'
                                                                                                      'Supports '
                                                                                                      'up '
                                                                                                      'to '
                                                                                                      '14 '
                                                                                                      'reference '
                                                                                                      'images. '
                                                                                                      'When '
                                                                                                      'provided, '
                                                                                                      'enables '
                                                                                                      'image-to-image\n'
                                                                                                      'editing/style-transfer '
                                                                                                      'mode '
                                                                                                      '(Google '
                                                                                                      'Gemini: '
                                                                                                      'same '
                                                                                                      'endpoint; '
                                                                                                      'FLUX: '
                                                                                                      'switches\n'
                                                                                                      'to '
                                                                                                      'the '
                                                                                                      '4B '
                                                                                                      'edit '
                                                                                                      'model). '
                                                                                                      'Ignored '
                                                                                                      'for '
                                                                                                      'SVG/Recraft '
                                                                                                      'output.\n',
                                                                                       'items': {'description': 'Original '
                                                                                                                'filename '
                                                                                                                '(embed_ref) '
                                                                                                                'of '
                                                                                                                'an '
                                                                                                                'uploaded '
                                                                                                                'image',
                                                                                                 'type': 'string'},
                                                                                       'type': 'array'}},
                                                   'required': ['prompt'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'generate',
  'skill_method_py': 'generate',
  'skill_method_ts': 'generate'},
 {'app_id': 'images',
  'app_namespace_py': 'images',
  'app_namespace_ts': 'images',
  'description': 'Quickly generate a draft/preview image from a text prompt and/or reference '
                 'images (image-to-image). Also use for: quick mockups, rough design concepts, '
                 'draft illustrations, sketches, quick visual previews, or any request for a '
                 'fast/rough image. When the user provides uploaded images as references '
                 '(embed_refs), pass them via reference_images. Do not use this for scam, spam, '
                 'fake-document, fake-endorsement, public-figure impersonation, or '
                 'watermark/detection-evasion requests.',
  'description_key': 'images.generate_draft.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of image generation '
                                                        'request objects for parallel processing '
                                                        '(up to 5 requests).\n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single image.\n'
                                                        'Example for single image: {"requests": '
                                                        '[{"prompt": "a cute cat"}]}\n'
                                                        "Each object must contain 'prompt' "
                                                        '(description of the image).\n',
                                         'items': {'properties': {'prompt': {'description': 'Description '
                                                                                            'of '
                                                                                            'the '
                                                                                            'image '
                                                                                            'to '
                                                                                            'generate',
                                                                             'type': 'string'},
                                                                  'reference_images': {'description': 'Optional '
                                                                                                      'list '
                                                                                                      'of '
                                                                                                      'reference '
                                                                                                      'image '
                                                                                                      'filenames '
                                                                                                      '(embed_refs) '
                                                                                                      'to '
                                                                                                      'use '
                                                                                                      'as '
                                                                                                      'visual\n'
                                                                                                      'references '
                                                                                                      'for '
                                                                                                      'this '
                                                                                                      'generation. '
                                                                                                      'Pass '
                                                                                                      'the '
                                                                                                      'exact '
                                                                                                      'embed_ref '
                                                                                                      'values '
                                                                                                      '(original\n'
                                                                                                      'filenames, '
                                                                                                      'e.g. '
                                                                                                      '"my_photo.jpg") '
                                                                                                      'from '
                                                                                                      'the '
                                                                                                      'toon '
                                                                                                      'blocks '
                                                                                                      'in '
                                                                                                      'the '
                                                                                                      'conversation.\n'
                                                                                                      'The '
                                                                                                      'server '
                                                                                                      'resolves '
                                                                                                      'all '
                                                                                                      'cryptographic '
                                                                                                      'and '
                                                                                                      'storage '
                                                                                                      'details '
                                                                                                      'automatically.\n'
                                                                                                      'Supports '
                                                                                                      'up '
                                                                                                      'to '
                                                                                                      '4 '
                                                                                                      'reference '
                                                                                                      'images. '
                                                                                                      'When '
                                                                                                      'provided, '
                                                                                                      'automatically '
                                                                                                      'switches '
                                                                                                      'to\n'
                                                                                                      'the '
                                                                                                      'FLUX.2 '
                                                                                                      '[klein] '
                                                                                                      '4B '
                                                                                                      'edit '
                                                                                                      'model '
                                                                                                      '(image-to-image, '
                                                                                                      '27 '
                                                                                                      'credits).\n',
                                                                                       'items': {'description': 'Original '
                                                                                                                'filename '
                                                                                                                '(embed_ref) '
                                                                                                                'of '
                                                                                                                'an '
                                                                                                                'uploaded '
                                                                                                                'image',
                                                                                                 'type': 'string'},
                                                                                       'type': 'array'}},
                                                   'required': ['prompt'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'generate_draft',
  'skill_method_py': 'generate_draft',
  'skill_method_ts': 'generateDraft'},
 {'app_id': 'mail',
  'app_namespace_py': 'mail',
  'app_namespace_ts': 'mail',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'app_skills.mail.search.description',
  'schema': {'additionalProperties': False,
             'properties': {'requests': {'description': 'REQUIRED: Array of mail search request '
                                                        'objects.\n'
                                                        'The query field is optional. If omitted '
                                                        'or empty, newest emails are returned '
                                                        'first.\n'
                                                        'Example: {"requests": [{"query": '
                                                        '"invoice", "limit": 10}]}\n'
                                                        'Example recent-first: {"requests": '
                                                        '[{"limit": 10}]}\n',
                                         'items': {'properties': {'id': {'description': 'Optional '
                                                                                        'request '
                                                                                        'id echoed '
                                                                                        'in '
                                                                                        'results',
                                                                         'type': ['string',
                                                                                  'integer']},
                                                                  'limit': {'default': 10,
                                                                            'description': 'Maximum '
                                                                                           'number '
                                                                                           'of '
                                                                                           'email '
                                                                                           'results '
                                                                                           'to '
                                                                                           'return',
                                                                            'maximum': 50,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'mailbox': {'description': 'Optional '
                                                                                             'mailbox '
                                                                                             'name '
                                                                                             '(defaults '
                                                                                             'to '
                                                                                             'INBOX)',
                                                                              'type': 'string'},
                                                                  'query': {'description': 'Optional '
                                                                                           'search '
                                                                                           'text '
                                                                                           '(subject/from/body). '
                                                                                           'Empty '
                                                                                           'means '
                                                                                           'recent-first '
                                                                                           'listing.',
                                                                            'type': 'string'}},
                                                   'type': 'object'},
                                         'minItems': 1,
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'maps',
  'app_namespace_py': 'maps',
  'app_namespace_ts': 'maps',
  'description': 'Search for places, businesses, restaurants, directions, locations.',
  'description_key': 'maps.search.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of search request objects '
                                                        'for parallel processing (up to 5 '
                                                        'requests). \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single search.\n'
                                                        'Example for single search: {"requests": '
                                                        '[{"query": "restaurants in Berlin"}]}\n'
                                                        'Example for multiple searches: '
                                                        '{"requests": [{"query": "restaurants in '
                                                        'Berlin"}, {"query": "museums in '
                                                        'Berlin"}]}\n'
                                                        "Each object must contain 'query' (search "
                                                        'query string), and can include optional '
                                                        'parameters (pageSize, languageCode, '
                                                        'locationBias, includedType, minRating, '
                                                        'openNow, includeReviews).\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        "not provided - you don't need to include "
                                                        'it.\n',
                                         'items': {'properties': {'includeReviews': {'default': False,
                                                                                     'description': 'If '
                                                                                                    'true, '
                                                                                                    'include '
                                                                                                    'user '
                                                                                                    'reviews '
                                                                                                    'in '
                                                                                                    'the '
                                                                                                    'response. '
                                                                                                    'Defaults '
                                                                                                    'to '
                                                                                                    'false '
                                                                                                    'to '
                                                                                                    'keep '
                                                                                                    'response '
                                                                                                    'size '
                                                                                                    'manageable. '
                                                                                                    'Reviews '
                                                                                                    'significantly '
                                                                                                    'increase '
                                                                                                    'response '
                                                                                                    'size.',
                                                                                     'type': 'boolean'},
                                                                  'includedType': {'description': 'Optional '
                                                                                                  'place '
                                                                                                  'type '
                                                                                                  'filter '
                                                                                                  '(e.g., '
                                                                                                  "'restaurant', "
                                                                                                  "'museum', "
                                                                                                  "'pharmacy'). "
                                                                                                  'See '
                                                                                                  'Google '
                                                                                                  'Places '
                                                                                                  'API '
                                                                                                  'place '
                                                                                                  'types '
                                                                                                  'documentation '
                                                                                                  'for '
                                                                                                  'full '
                                                                                                  'list.',
                                                                                   'type': 'string'},
                                                                  'languageCode': {'default': 'en',
                                                                                   'description': 'Language '
                                                                                                  'code '
                                                                                                  'for '
                                                                                                  'results '
                                                                                                  '(ISO '
                                                                                                  '639-1, '
                                                                                                  'e.g., '
                                                                                                  "'en', "
                                                                                                  "'es', "
                                                                                                  "'fr', "
                                                                                                  "'de'). "
                                                                                                  'Defaults '
                                                                                                  'to '
                                                                                                  "'en' "
                                                                                                  'if '
                                                                                                  'not '
                                                                                                  'specified.',
                                                                                   'type': 'string'},
                                                                  'locationBias': {'description': 'Optional '
                                                                                                  'location '
                                                                                                  'bias '
                                                                                                  'to '
                                                                                                  'prioritize '
                                                                                                  'results '
                                                                                                  'near '
                                                                                                  'a '
                                                                                                  'specific '
                                                                                                  'area. '
                                                                                                  'Can '
                                                                                                  'be '
                                                                                                  'a '
                                                                                                  'circle '
                                                                                                  '(center '
                                                                                                  '+ '
                                                                                                  'radius) '
                                                                                                  'or '
                                                                                                  'rectangle '
                                                                                                  '(viewport).',
                                                                                   'properties': {'circle': {'properties': {'center': {'properties': {'latitude': {'type': 'number'},
                                                                                                                                                      'longitude': {'type': 'number'}},
                                                                                                                                       'type': 'object'},
                                                                                                                            'radius': {'description': 'Radius '
                                                                                                                                                      'in '
                                                                                                                                                      'meters '
                                                                                                                                                      '(0.0 '
                                                                                                                                                      'to '
                                                                                                                                                      '50000.0)',
                                                                                                                                       'type': 'number'}},
                                                                                                             'type': 'object'},
                                                                                                  'rectangle': {'properties': {'high': {'properties': {'latitude': {'type': 'number'},
                                                                                                                                                       'longitude': {'type': 'number'}},
                                                                                                                                        'type': 'object'},
                                                                                                                               'low': {'properties': {'latitude': {'type': 'number'},
                                                                                                                                                      'longitude': {'type': 'number'}},
                                                                                                                                       'type': 'object'}},
                                                                                                                'type': 'object'}},
                                                                                   'type': 'object'},
                                                                  'minRating': {'description': 'Minimum '
                                                                                               'rating '
                                                                                               'filter '
                                                                                               '(0.0 '
                                                                                               'to '
                                                                                               '5.0, '
                                                                                               'increments '
                                                                                               'of '
                                                                                               '0.5). '
                                                                                               'Only '
                                                                                               'places '
                                                                                               'with '
                                                                                               'rating '
                                                                                               '>= '
                                                                                               'minRating '
                                                                                               'will '
                                                                                               'be '
                                                                                               'returned.',
                                                                                'maximum': 5.0,
                                                                                'minimum': 0.0,
                                                                                'type': 'number'},
                                                                  'openNow': {'default': False,
                                                                              'description': 'If '
                                                                                             'true, '
                                                                                             'return '
                                                                                             'only '
                                                                                             'places '
                                                                                             'that '
                                                                                             'are '
                                                                                             'currently '
                                                                                             'open. '
                                                                                             'Defaults '
                                                                                             'to '
                                                                                             'false.',
                                                                              'type': 'boolean'},
                                                                  'pageSize': {'default': 10,
                                                                               'description': 'Number '
                                                                                              'of '
                                                                                              'results '
                                                                                              'to '
                                                                                              'return '
                                                                                              'per '
                                                                                              'request '
                                                                                              '(max '
                                                                                              '20)',
                                                                               'maximum': 20,
                                                                               'minimum': 1,
                                                                               'type': 'integer'},
                                                                  'query': {'description': 'Text '
                                                                                           'query '
                                                                                           'string '
                                                                                           'to '
                                                                                           'search '
                                                                                           'for '
                                                                                           'places '
                                                                                           '(e.g., '
                                                                                           '"restaurants '
                                                                                           'in '
                                                                                           'Berlin", '
                                                                                           '"museums '
                                                                                           'near '
                                                                                           'Times '
                                                                                           'Square")',
                                                                            'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'math',
  'app_namespace_py': 'math',
  'app_namespace_ts': 'math',
  'description': 'MANDATORY: Use this skill for ALL mathematical calculations without exception. '
                 'This includes simple arithmetic such as addition, subtraction, multiplication '
                 '(written as *, x, or ×), division, and parenthesised expressions like (4x22x7)/2 '
                 'or (100+50)*3/2. Also use for algebra, trigonometry, calculus, unit conversions, '
                 'symbolic simplification, equation solving, derivatives, and integrals. NEVER '
                 'attempt to compute a numeric result yourself — always call this skill so results '
                 'are guaranteed to be ex',
  'description_key': 'math.calculate.description',
  'schema': {'properties': {'expression': {'description': 'The mathematical expression, equation, '
                                                          'or operation to evaluate. Examples: - '
                                                          'Arithmetic: "3.14159 * (42.7)^2 / '
                                                          'cos(0.3)" - Symbolic simplify: '
                                                          '"simplify((x^2 - 1) / (x - 1))" - Solve '
                                                          'equation: "solve(x^2 - 4*x + 3, x)" - '
                                                          'Derivative: "diff(sin(x) * exp(x), x)" '
                                                          '- Integral: "integrate(x^2 * log(x), '
                                                          'x)" - Unit conversion: "convert(100, '
                                                          'kg, lbs)" - With context vars: "E = m * '
                                                          'c^2 where m=1, c=299792458"\n',
                                           'type': 'string'},
                            'mode': {'default': 'auto',
                                     'description': "Evaluation mode. 'auto' (default) detects the "
                                                    'appropriate mode from the expression. '
                                                    "'numeric' forces numerical evaluation. "
                                                    "'symbolic' forces symbolic computation. "
                                                    "'solve' solves an equation for a variable. "
                                                    "'simplify' simplifies an algebraic "
                                                    "expression. 'diff' computes derivative. "
                                                    "'integrate' computes integral. 'convert' "
                                                    'converts units.\n',
                                     'enum': ['auto',
                                              'numeric',
                                              'symbolic',
                                              'solve',
                                              'simplify',
                                              'diff',
                                              'integrate',
                                              'convert'],
                                     'type': 'string'},
                            'precision': {'default': 15,
                                          'description': 'Number of significant digits for numeric '
                                                         'results. Defaults to 15. Use higher '
                                                         'values (e.g. 50) for high-precision '
                                                         'calculations.\n',
                                          'maximum': 100,
                                          'minimum': 1,
                                          'type': 'integer'},
                            'title': {'description': 'A short human-readable title that explains '
                                                     'why this calculation is being made. This is '
                                                     'shown in the embed preview, so prefer '
                                                     'concise context like "Bike time to the Moon" '
                                                     'or "Monthly mortgage estimate".\n',
                                      'type': 'string'},
                            'variable': {'default': 'x',
                                         'description': 'The variable to differentiate or '
                                                        'integrate with respect to, or to solve '
                                                        "for. Defaults to 'x'. Only needed when "
                                                        "mode is 'diff', 'integrate', or "
                                                        "'solve'.\n",
                                         'type': 'string'}},
             'required': ['expression'],
             'type': 'object'},
  'skill_id': 'calculate',
  'skill_method_py': 'calculate',
  'skill_method_ts': 'calculate'},
 {'app_id': 'models3d',
  'app_namespace_py': 'models3d',
  'app_namespace_ts': 'models3d',
  'description': 'Search public 3D model catalogs for existing models. Use this when the user '
                 'wants to find, browse, compare, or link to existing 3D-printable or downloadable '
                 '3D models. Do not use it to generate new models.',
  'description_key': 'app_skills.models3d.search.description',
  'schema': {'properties': {'requests': {'description': 'Array of 3D model search requests. Each '
                                                        'request searches public 3D model catalogs '
                                                        'and returns preview-only result cards.\n',
                                         'items': {'properties': {'count': {'default': 10,
                                                                            'description': 'Maximum '
                                                                                           'total '
                                                                                           'results '
                                                                                           'to '
                                                                                           'return '
                                                                                           'after '
                                                                                           'merging '
                                                                                           'providers.',
                                                                            'maximum': 20,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'free_only': {'default': False,
                                                                                'description': 'Return '
                                                                                               'only '
                                                                                               'results '
                                                                                               'that '
                                                                                               'the '
                                                                                               'provider '
                                                                                               'marks '
                                                                                               'as '
                                                                                               'free.',
                                                                                'type': 'boolean'},
                                                                  'providers': {'description': 'Optional '
                                                                                               'provider '
                                                                                               'filter. '
                                                                                               'Defaults '
                                                                                               'to '
                                                                                               'Printables.',
                                                                                'items': {'enum': ['Printables'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                                  'query': {'description': 'Search '
                                                                                           'query, '
                                                                                           'e.g. '
                                                                                           '"benchy", '
                                                                                           '"phone '
                                                                                           'stand", '
                                                                                           'or '
                                                                                           '"desk '
                                                                                           'cable '
                                                                                           'clip".',
                                                                            'type': 'string'},
                                                                  'sort': {'default': 'best_match',
                                                                           'description': 'Sorting '
                                                                                          'strategy '
                                                                                          'applied '
                                                                                          'after '
                                                                                          'provider '
                                                                                          'results '
                                                                                          'are '
                                                                                          'merged.',
                                                                           'enum': ['best_match',
                                                                                    'popular',
                                                                                    'downloads',
                                                                                    'newest'],
                                                                           'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'music',
  'app_namespace_py': 'music',
  'app_namespace_ts': 'music',
  'description': 'Generate music from a text prompt, including full songs, instrumental tracks, '
                 'background music, loops, jingles, lyric-based songs, and soundtrack cues. Use '
                 'this when the user asks to create music or background music. Do not use this to '
                 'imitate the voice, vocals, cadence, or persona of a real public figure, living '
                 'artist, famous educator, or recognizable person. Use original voices and styles '
                 'only, and reject scams, spam, or detection evasion.',
  'description_key': 'app_skills.music.generate.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of music generation '
                                                        'request objects. Each object must\n'
                                                        'include a prompt and can specify '
                                                        'duration_seconds, mode, lyrics, style,\n'
                                                        'negative_prompt, seed, and model.\n',
                                         'items': {'properties': {'duration_seconds': {'default': 30,
                                                                                       'description': 'Target '
                                                                                                      'duration '
                                                                                                      'in '
                                                                                                      'seconds. '
                                                                                                      'Lyria '
                                                                                                      '3 '
                                                                                                      'Clip '
                                                                                                      'is '
                                                                                                      '30s; '
                                                                                                      'Lyria '
                                                                                                      '3 '
                                                                                                      'Pro '
                                                                                                      'supports '
                                                                                                      'longer '
                                                                                                      'tracks '
                                                                                                      'in '
                                                                                                      'preview.',
                                                                                       'maximum': 184,
                                                                                       'minimum': 3,
                                                                                       'type': 'integer'},
                                                                  'lyrics': {'description': 'Optional '
                                                                                            'lyrics '
                                                                                            'to '
                                                                                            'include '
                                                                                            'for '
                                                                                            'vocal/song '
                                                                                            'generation.',
                                                                             'type': 'string'},
                                                                  'mode': {'default': 'background',
                                                                           'description': 'Desired '
                                                                                          'music '
                                                                                          'type.',
                                                                           'enum': ['song',
                                                                                    'instrumental',
                                                                                    'background',
                                                                                    'loop',
                                                                                    'jingle'],
                                                                           'type': 'string'},
                                                                  'model': {'default': 'lyria-3-pro-preview',
                                                                            'description': 'Google '
                                                                                           'Lyria '
                                                                                           'model. '
                                                                                           'Prefer '
                                                                                           'lyria-3-pro-preview '
                                                                                           'for '
                                                                                           'latest '
                                                                                           'quality.',
                                                                            'enum': ['lyria-3-pro-preview',
                                                                                     'lyria-3-clip-preview',
                                                                                     'lyria-002'],
                                                                            'type': 'string'},
                                                                  'negative_prompt': {'description': 'Optional '
                                                                                                     'sounds, '
                                                                                                     'genres, '
                                                                                                     'instruments, '
                                                                                                     'or '
                                                                                                     'qualities '
                                                                                                     'to '
                                                                                                     'avoid.',
                                                                                      'type': 'string'},
                                                                  'prompt': {'description': 'Text '
                                                                                            'description '
                                                                                            'of '
                                                                                            'the '
                                                                                            'music '
                                                                                            'to '
                                                                                            'generate.',
                                                                             'type': 'string'},
                                                                  'seed': {'description': 'Optional '
                                                                                          'seed '
                                                                                          'for '
                                                                                          'more '
                                                                                          'reproducible '
                                                                                          'output '
                                                                                          'when '
                                                                                          'supported.',
                                                                           'type': 'integer'},
                                                                  'style': {'description': 'Optional '
                                                                                           'genre, '
                                                                                           'mood, '
                                                                                           'instrumentation, '
                                                                                           'tempo, '
                                                                                           'or '
                                                                                           'production '
                                                                                           'style.',
                                                                            'type': 'string'}},
                                                   'required': ['prompt'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'generate',
  'skill_method_py': 'generate',
  'skill_method_ts': 'generate'},
 {'app_id': 'news',
  'app_namespace_py': 'news',
  'app_namespace_ts': 'news',
  'description': 'Search for news articles, current events, headlines, announcements.',
  'description_key': 'news.search.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of search request objects '
                                                        'for parallel processing (up to 5 '
                                                        'requests). \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single search.\n'
                                                        'Example for single search: {"requests": '
                                                        '[{"query": "iPhone news"}]}\n'
                                                        'Example for multiple searches: '
                                                        '{"requests": [{"query": "iPhone news"}, '
                                                        '{"query": "MacBook news"}]}\n'
                                                        "Each object must contain 'query' (search "
                                                        'query string), and can include optional '
                                                        'parameters (count, country, search_lang, '
                                                        'safesearch, freshness).\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        "not provided - you don't need to include "
                                                        'it.\n',
                                         'items': {'properties': {'count': {'default': 6,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'results '
                                                                                           'for '
                                                                                           'this '
                                                                                           'request '
                                                                                           '(max '
                                                                                           '20)',
                                                                            'maximum': 20,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'country': {'default': 'us',
                                                                              'description': 'Country '
                                                                                             'code '
                                                                                             'for '
                                                                                             'localized '
                                                                                             'results. '
                                                                                             'Must '
                                                                                             'be '
                                                                                             'one '
                                                                                             'of: '
                                                                                             'AR, '
                                                                                             'AU, '
                                                                                             'AT, '
                                                                                             'BE, '
                                                                                             'BR, '
                                                                                             'CA, '
                                                                                             'CL, '
                                                                                             'DK, '
                                                                                             'FI, '
                                                                                             'FR, '
                                                                                             'DE, '
                                                                                             'GR, '
                                                                                             'HK, '
                                                                                             'IN, '
                                                                                             'ID, '
                                                                                             'IT, '
                                                                                             'JP, '
                                                                                             'KR, '
                                                                                             'MY, '
                                                                                             'MX, '
                                                                                             'NL, '
                                                                                             'NZ, '
                                                                                             'NO, '
                                                                                             'CN, '
                                                                                             'PL, '
                                                                                             'PT, '
                                                                                             'PH, '
                                                                                             'RU, '
                                                                                             'SA, '
                                                                                             'ZA, '
                                                                                             'ES, '
                                                                                             'SE, '
                                                                                             'CH, '
                                                                                             'TW, '
                                                                                             'TR, '
                                                                                             'GB, '
                                                                                             'US, '
                                                                                             'or '
                                                                                             'ALL '
                                                                                             '(case-insensitive). '
                                                                                             'Defaults '
                                                                                             'to '
                                                                                             "'us' "
                                                                                             'if '
                                                                                             'invalid.',
                                                                              'enum': ['AR',
                                                                                       'AU',
                                                                                       'AT',
                                                                                       'BE',
                                                                                       'BR',
                                                                                       'CA',
                                                                                       'CL',
                                                                                       'DK',
                                                                                       'FI',
                                                                                       'FR',
                                                                                       'DE',
                                                                                       'GR',
                                                                                       'HK',
                                                                                       'IN',
                                                                                       'ID',
                                                                                       'IT',
                                                                                       'JP',
                                                                                       'KR',
                                                                                       'MY',
                                                                                       'MX',
                                                                                       'NL',
                                                                                       'NZ',
                                                                                       'NO',
                                                                                       'CN',
                                                                                       'PL',
                                                                                       'PT',
                                                                                       'PH',
                                                                                       'RU',
                                                                                       'SA',
                                                                                       'ZA',
                                                                                       'ES',
                                                                                       'SE',
                                                                                       'CH',
                                                                                       'TW',
                                                                                       'TR',
                                                                                       'GB',
                                                                                       'US',
                                                                                       'ALL',
                                                                                       'ar',
                                                                                       'au',
                                                                                       'at',
                                                                                       'be',
                                                                                       'br',
                                                                                       'ca',
                                                                                       'cl',
                                                                                       'dk',
                                                                                       'fi',
                                                                                       'fr',
                                                                                       'de',
                                                                                       'gr',
                                                                                       'hk',
                                                                                       'in',
                                                                                       'id',
                                                                                       'it',
                                                                                       'jp',
                                                                                       'kr',
                                                                                       'my',
                                                                                       'mx',
                                                                                       'nl',
                                                                                       'nz',
                                                                                       'no',
                                                                                       'cn',
                                                                                       'pl',
                                                                                       'pt',
                                                                                       'ph',
                                                                                       'ru',
                                                                                       'sa',
                                                                                       'za',
                                                                                       'es',
                                                                                       'se',
                                                                                       'ch',
                                                                                       'tw',
                                                                                       'tr',
                                                                                       'gb',
                                                                                       'us',
                                                                                       'all'],
                                                                              'type': 'string'},
                                                                  'filter_tabloids': {'default': True,
                                                                                      'description': 'Filter '
                                                                                                     'out '
                                                                                                     'tabloid/boulevard '
                                                                                                     'media '
                                                                                                     'sources '
                                                                                                     '(e.g., '
                                                                                                     'BILD, '
                                                                                                     'Daily '
                                                                                                     'Mail, '
                                                                                                     'TMZ, '
                                                                                                     'The '
                                                                                                     'Sun) '
                                                                                                     'from '
                                                                                                     'results. '
                                                                                                     'Enabled '
                                                                                                     'by '
                                                                                                     'default '
                                                                                                     'for '
                                                                                                     'quality '
                                                                                                     'news. '
                                                                                                     'Set '
                                                                                                     'to '
                                                                                                     'false '
                                                                                                     'ONLY '
                                                                                                     'if '
                                                                                                     'the '
                                                                                                     'user '
                                                                                                     'explicitly '
                                                                                                     'asks '
                                                                                                     'for '
                                                                                                     'tabloid '
                                                                                                     'sources.',
                                                                                      'type': 'boolean'},
                                                                  'freshness': {'default': 'pw',
                                                                                'description': 'Filter '
                                                                                               'by '
                                                                                               'freshness '
                                                                                               '- '
                                                                                               '"pd" '
                                                                                               '(past '
                                                                                               '24 '
                                                                                               'hours), '
                                                                                               '"pw" '
                                                                                               '(past '
                                                                                               'week), '
                                                                                               '"pm" '
                                                                                               '(past '
                                                                                               'month), '
                                                                                               '"py" '
                                                                                               '(past '
                                                                                               'year). '
                                                                                               'Defaults '
                                                                                               'to '
                                                                                               '"pw" '
                                                                                               '(past '
                                                                                               'week) '
                                                                                               'to '
                                                                                               'prioritize '
                                                                                               'recent '
                                                                                               'news '
                                                                                               'content.',
                                                                                'enum': ['pd',
                                                                                         'pw',
                                                                                         'pm',
                                                                                         'py'],
                                                                                'type': 'string'},
                                                                  'query': {'description': 'Search '
                                                                                           'query '
                                                                                           'string',
                                                                            'type': 'string'},
                                                                  'safesearch': {'default': 'moderate',
                                                                                 'description': 'Safe '
                                                                                                'search '
                                                                                                'level',
                                                                                 'enum': ['off',
                                                                                          'moderate',
                                                                                          'strict'],
                                                                                 'type': 'string'},
                                                                  'search_lang': {'default': 'en',
                                                                                  'description': 'Language '
                                                                                                 'code '
                                                                                                 'for '
                                                                                                 'search '
                                                                                                 '(ISO '
                                                                                                 '639-1, '
                                                                                                 'e.g., '
                                                                                                 "'en', "
                                                                                                 "'es', "
                                                                                                 "'fr')",
                                                                                  'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'nutrition',
  'app_namespace_py': 'nutrition',
  'app_namespace_ts': 'nutrition',
  'description': 'Search Edamam for recipes by natural-language query and nutrition filters. '
                 'Returns recipe details with ingredients, step-by-step instructions, images, '
                 'source links, and nutrition metadata. Recipes without instructions are filtered '
                 'out. Best for: recipe recommendations, meal planning, dietary filtering, and '
                 'cooking guidance.',
  'description_key': 'app_skills.nutrition.search_recipes.description',
  'schema': {'properties': {'requests': {'description': 'Array of recipe search requests. Each '
                                                        'request searches for recipes matching a '
                                                        'free-text query and optional Edamam '
                                                        'filters.\n',
                                         'items': {'properties': {'calories': {'description': 'Optional '
                                                                                              'calories '
                                                                                              'range, '
                                                                                              'e.g. '
                                                                                              '"100-600".',
                                                                               'type': 'string'},
                                                                  'cuisine_type': {'description': 'Optional '
                                                                                                  'cuisine '
                                                                                                  'filters '
                                                                                                  'such '
                                                                                                  'as '
                                                                                                  'Italian, '
                                                                                                  'Japanese, '
                                                                                                  'Mexican.',
                                                                                   'items': {'type': 'string'},
                                                                                   'type': 'array'},
                                                                  'diet': {'description': 'Optional '
                                                                                          'Edamam '
                                                                                          'diet '
                                                                                          'labels '
                                                                                          'such as '
                                                                                          'balanced, '
                                                                                          'high-fiber, '
                                                                                          'high-protein, '
                                                                                          'low-carb, '
                                                                                          'low-fat, '
                                                                                          'low-sodium.\n',
                                                                           'items': {'type': 'string'},
                                                                           'type': 'array'},
                                                                  'dish_type': {'description': 'Optional '
                                                                                               'dish '
                                                                                               'filters '
                                                                                               'such '
                                                                                               'as '
                                                                                               'Main '
                                                                                               'course, '
                                                                                               'Soup, '
                                                                                               'Salad, '
                                                                                               'Pancake.',
                                                                                'items': {'type': 'string'},
                                                                                'type': 'array'},
                                                                  'excluded': {'description': 'Optional '
                                                                                              'ingredients '
                                                                                              'or '
                                                                                              'terms '
                                                                                              'to '
                                                                                              'exclude '
                                                                                              'from '
                                                                                              'recipes.',
                                                                               'items': {'type': 'string'},
                                                                               'type': 'array'},
                                                                  'health': {'description': 'Optional '
                                                                                            'Edamam '
                                                                                            'health '
                                                                                            'labels '
                                                                                            'such '
                                                                                            'as '
                                                                                            'vegan, '
                                                                                            'vegetarian, '
                                                                                            'gluten-free, '
                                                                                            'dairy-free, '
                                                                                            'keto-friendly, '
                                                                                            'peanut-free, '
                                                                                            'tree-nut-free.\n',
                                                                             'items': {'type': 'string'},
                                                                             'type': 'array'},
                                                                  'ingredients': {'description': 'Optional '
                                                                                                 'ingredient-count '
                                                                                                 'range, '
                                                                                                 'e.g. '
                                                                                                 '"5-10".',
                                                                                  'type': 'string'},
                                                                  'max_results': {'default': 6,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'recipes '
                                                                                                 'to '
                                                                                                 'return '
                                                                                                 'with '
                                                                                                 'full '
                                                                                                 'details '
                                                                                                 '(1-10, '
                                                                                                 'default '
                                                                                                 '6). '
                                                                                                 'Each '
                                                                                                 'returned '
                                                                                                 'result '
                                                                                                 'includes '
                                                                                                 'ingredients, '
                                                                                                 'step-by-step '
                                                                                                 'instructions, '
                                                                                                 'image '
                                                                                                 'data, '
                                                                                                 'source '
                                                                                                 'attribution, '
                                                                                                 'and '
                                                                                                 'nutrition '
                                                                                                 'metadata.\n',
                                                                                  'type': 'integer'},
                                                                  'meal_type': {'description': 'Optional '
                                                                                               'meal '
                                                                                               'filters '
                                                                                               'such '
                                                                                               'as '
                                                                                               'Breakfast, '
                                                                                               'Dinner, '
                                                                                               'Lunch, '
                                                                                               'Snack.',
                                                                                'items': {'type': 'string'},
                                                                                'type': 'array'},
                                                                  'query': {'description': 'Free-text '
                                                                                           'recipe '
                                                                                           'query, '
                                                                                           'e.g. '
                                                                                           '"quick '
                                                                                           'vegan '
                                                                                           'pasta", '
                                                                                           '"gluten-free '
                                                                                           'pancakes", '
                                                                                           'or '
                                                                                           '"miso '
                                                                                           'salmon".\n',
                                                                            'type': 'string'},
                                                                  'time': {'description': 'Optional '
                                                                                          'cooking/prep '
                                                                                          'time '
                                                                                          'range, '
                                                                                          'e.g. '
                                                                                          '"1-30".',
                                                                           'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_recipes',
  'skill_method_py': 'search_recipes',
  'skill_method_ts': 'searchRecipes'},
 {'app_id': 'openmates',
  'app_namespace_py': 'openmates',
  'app_namespace_ts': 'openmates',
  'description': 'Use when the user has explicitly agreed to anonymously share a summary of their '
                 'intended use cases with the OpenMates team to help improve the product. NEVER '
                 'call this without clear user consent.',
  'description_key': 'openmates_app.share_usecase.description',
  'schema': {'properties': {'language': {'description': 'ISO 639-1 language code of the '
                                                        "conversation (e.g., 'en', 'de')",
                                         'type': 'string'},
                            'summary': {'description': 'A brief summary (2-5 sentences) of what '
                                                       'the user wants to use OpenMates for, as '
                                                       'discussed in the conversation. Should '
                                                       'capture the key use cases and interests.\n',
                                        'type': 'string'}},
             'required': ['summary', 'language'],
             'type': 'object'},
  'skill_id': 'share-usecase',
  'skill_method_py': 'share_usecase',
  'skill_method_ts': 'shareUsecase'},
 {'app_id': 'openmates',
  'app_namespace_py': 'openmates',
  'app_namespace_ts': 'openmates',
  'description': 'Use when the user shares an openmates.org/docs URL, or asks to read a specific '
                 'OpenMates documentation page. Automatically triggered when an openmates docs URL '
                 'is detected in the conversation.',
  'description_key': 'openmates_app.get_docs.description',
  'schema': {'properties': {'url': {'description': 'An openmates.org/docs URL or a docs slug path '
                                                   "(e.g., 'architecture/chats' or "
                                                   "'https://openmates.org/docs/architecture/chats')\n",
                                    'type': 'string'}},
             'required': ['url'],
             'type': 'object'},
  'skill_id': 'get-docs',
  'skill_method_py': 'get_docs',
  'skill_method_ts': 'getDocs'},
 {'app_id': 'openmates',
  'app_namespace_py': 'openmates',
  'app_namespace_ts': 'openmates',
  'description': 'Use when the user asks about OpenMates features, setup, architecture, or '
                 'documentation. Searches across all OpenMates documentation to find relevant '
                 'pages.',
  'description_key': 'openmates_app.search_docs.description',
  'schema': {'properties': {'query': {'description': 'Search terms to find in OpenMates '
                                                     'documentation',
                                      'type': 'string'}},
             'required': ['query'],
             'type': 'object'},
  'skill_id': 'search-docs',
  'skill_method_py': 'search_docs',
  'skill_method_ts': 'searchDocs'},
 {'app_id': 'pdf',
  'app_namespace_py': 'pdf',
  'app_namespace_ts': 'pdf',
  'description': 'Load and read the raw text content (markdown) of specific pages from an uploaded '
                 'PDF document. Use when the user asks what a PDF says, wants you to summarise '
                 'sections, or requests information that is likely textual (paragraphs, tables, '
                 'headings). The embed TOON content includes a TOC and per-page token estimates — '
                 'use them to select the most relevant pages. Limits output to 50 000 tokens; call '
                 'again for remaining pages if needed. Pass the exact embed_ref (original '
                 'filename) from the toon block —',
  'description_key': 'pdf.read.description',
  'schema': {'properties': {'file_path': {'description': 'The original filename of the PDF (e.g. '
                                                         '"report.pdf"). Use the exact embed_ref '
                                                         'value from the toon block. The server '
                                                         'resolves all cryptographic and storage '
                                                         'details from this filename '
                                                         'automatically.\n',
                                          'type': 'string'},
                            'pages': {'description': '1-indexed page numbers to read (e.g. [1, 2, '
                                                     '3]). If omitted, reads from page 1 onwards '
                                                     'up to the token budget.',
                                      'items': {'type': 'integer'},
                                      'type': 'array'}},
             'required': ['file_path'],
             'type': 'object'},
  'skill_id': 'read',
  'skill_method_py': 'read',
  'skill_method_ts': 'read'},
 {'app_id': 'pdf',
  'app_namespace_py': 'pdf',
  'app_namespace_ts': 'pdf',
  'description': 'Search for specific text, keywords, or phrases across all pages of an uploaded '
                 'PDF. Returns matching text blocks with surrounding context and page numbers. Use '
                 'when the user asks to find where something is mentioned in the document, or when '
                 'a targeted keyword search is faster than reading entire sections. No LLM call '
                 'required — pure text search over the OCR data. Pass the exact embed_ref '
                 '(original filename) from the toon block as file_path.',
  'description_key': 'pdf.search.description',
  'schema': {'properties': {'context_chars': {'description': 'Number of characters of surrounding '
                                                             'context to include per match '
                                                             '(default: 200).',
                                              'type': 'integer'},
                            'file_path': {'description': 'The original filename of the PDF. Use '
                                                         'the exact embed_ref from the toon block. '
                                                         'The server resolves all cryptographic '
                                                         'and storage details automatically.\n',
                                          'type': 'string'},
                            'query': {'description': 'The search query string (case-insensitive '
                                                     'substring match).',
                                      'type': 'string'}},
             'required': ['file_path', 'query'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'pdf',
  'app_namespace_py': 'pdf',
  'app_namespace_ts': 'pdf',
  'description': 'View one or more page screenshots from an uploaded PDF and return them as '
                 'multimodal image blocks so the main inference model can see the pages directly. '
                 'Use when the user asks about the visual layout, diagrams, charts, figures, or '
                 'images on specific pages. Also useful when text OCR may have been imperfect '
                 '(e.g. complex tables, mathematical notation, handwriting). Up to 5 pages can be '
                 'viewed per call. Pass the exact embed_ref (original filename) from the toon '
                 'block as file_path — the server reso',
  'description_key': 'pdf.view.skill_description',
  'schema': {'properties': {'file_path': {'description': 'The original filename of the PDF. Use '
                                                         'the exact embed_ref from the toon block. '
                                                         'The server resolves all cryptographic '
                                                         'and storage details automatically.\n',
                                          'type': 'string'},
                            'pages': {'description': '1-indexed page numbers to view (max 5). '
                                                     'Example: [1, 2].',
                                      'items': {'type': 'integer'},
                                      'type': 'array'},
                            'query': {'description': "The user's question or instruction about the "
                                                     'page(s).',
                                      'type': 'string'}},
             'required': ['file_path', 'pages', 'query'],
             'type': 'object'},
  'skill_id': 'view',
  'skill_method_py': 'view',
  'skill_method_ts': 'view'},
 {'app_id': 'reminder',
  'app_namespace_py': 'reminder',
  'app_namespace_ts': 'reminder',
  'description': 'Schedule, create, or set up reminders for the user. Handles one-time and '
                 'recurring reminders (e.g., "every morning", "daily at 9am", "weekly", '
                 '"monthly"). Use when user wants to be reminded, notified, or alerted about '
                 'something at a specific time or on a recurring schedule. Also use for automating '
                 'tasks like "get news every day" or "summarize updates weekly".',
  'description_key': 'reminder.set_reminder.description',
  'schema': {'properties': {'new_chat_title': {'description': 'Title for the new chat. Required if '
                                                              "target_type is 'new_chat'.",
                                               'type': 'string'},
                            'prompt': {'description': 'The reminder message/prompt that will be '
                                                      'shown when the reminder fires',
                                       'type': 'string'},
                            'random_end_date': {'description': 'End date for random window '
                                                               '(YYYY-MM-DD). Required if '
                                                               "trigger_type is 'random'.",
                                                'type': 'string'},
                            'random_start_date': {'description': 'Start date for random window '
                                                                 '(YYYY-MM-DD). Required if '
                                                                 "trigger_type is 'random'.",
                                                  'type': 'string'},
                            'random_time_end': {'description': 'Latest time of day for random '
                                                               'trigger (HH:MM, 24h format, e.g., '
                                                               "'14:00'). Optional for random "
                                                               'triggers.',
                                                'type': 'string'},
                            'random_time_start': {'description': 'Earliest time of day for random '
                                                                 'trigger (HH:MM, 24h format, '
                                                                 "e.g., '10:00'). Optional for "
                                                                 'random triggers.',
                                                  'type': 'string'},
                            'repeat': {'description': 'Configuration for repeating reminders. Omit '
                                                      'for one-time reminders.',
                                       'properties': {'day_of_month': {'description': 'For monthly '
                                                                                      'type: day '
                                                                                      'of the '
                                                                                      'month '
                                                                                      '(1-31)',
                                                                       'maximum': 31,
                                                                       'minimum': 1,
                                                                       'type': 'integer'},
                                                      'day_of_week': {'description': 'For weekly '
                                                                                     'type: '
                                                                                     '0=Monday, '
                                                                                     '6=Sunday',
                                                                      'maximum': 6,
                                                                      'minimum': 0,
                                                                      'type': 'integer'},
                                                      'end_date': {'description': 'Optional: stop '
                                                                                  'repeating after '
                                                                                  'this date '
                                                                                  '(YYYY-MM-DD)',
                                                                   'type': 'string'},
                                                      'interval': {'description': 'For custom '
                                                                                  'type: repeat '
                                                                                  'every N units',
                                                                   'minimum': 1,
                                                                   'type': 'integer'},
                                                      'interval_unit': {'description': 'For custom '
                                                                                       'type: unit '
                                                                                       'of the '
                                                                                       'interval',
                                                                        'enum': ['days',
                                                                                 'weeks',
                                                                                 'months'],
                                                                        'type': 'string'},
                                                      'max_occurrences': {'description': 'Optional: '
                                                                                         'maximum '
                                                                                         'number '
                                                                                         'of times '
                                                                                         'to fire',
                                                                          'minimum': 1,
                                                                          'type': 'integer'},
                                                      'type': {'description': 'Type of repeat '
                                                                              'schedule',
                                                               'enum': ['daily',
                                                                        'weekly',
                                                                        'monthly',
                                                                        'custom'],
                                                               'type': 'string'}},
                                       'required': ['type'],
                                       'type': 'object'},
                            'response_type': {'default': 'simple',
                                              'description': "'simple' = notification-only: no AI "
                                                             'response is generated, just a '
                                                             'notification, email, and a visual '
                                                             'marker in the chat history. Use for '
                                                             "passive nudges ('remind me about "
                                                             "this', 'ping me tomorrow'). 'full' = "
                                                             'action trigger: the AI executes a '
                                                             'task when the reminder fires. Use '
                                                             'ONLY when the user wants the AI to '
                                                             "actively do something ('summarize "
                                                             "the news every morning', 'give me an "
                                                             "update on X'). Default is 'simple'.",
                                              'enum': ['simple', 'full'],
                                              'type': 'string'},
                            'target_embed_app_id': {'description': 'App ID for the embed target. '
                                                                   'Optional; used by client '
                                                                   'display.',
                                                    'type': 'string'},
                            'target_embed_id': {'description': 'Embed ID to open when target_type '
                                                               "is 'embed'.",
                                                'type': 'string'},
                            'target_embed_title': {'description': 'Display title for the embed '
                                                                  'target. Optional; used by '
                                                                  'client display.',
                                                   'type': 'string'},
                            'target_type': {'default': 'existing_chat',
                                            'description': "'existing_chat' sends a follow-up in "
                                                           'the current chat and is the default '
                                                           'for reminders requested from chat, '
                                                           "'new_chat' creates a new chat when the "
                                                           'user explicitly asks for a new chat or '
                                                           "standalone reminder thread, 'embed' "
                                                           'opens a saved embed fullscreen',
                                            'enum': ['new_chat', 'existing_chat', 'embed'],
                                            'type': 'string'},
                            'timezone': {'description': "User's timezone (e.g., 'Europe/Berlin', "
                                                        "'America/New_York'). Required.",
                                         'type': 'string'},
                            'trigger_datetime': {'description': 'ISO 8601 datetime for specific '
                                                                'trigger (e.g., '
                                                                "'2026-02-05T14:30:00'). Required "
                                                                "if trigger_type is 'specific'.",
                                                 'type': 'string'},
                            'trigger_type': {'description': "'specific' for exact datetime, "
                                                            "'random' for random time within a "
                                                            'window',
                                             'enum': ['specific', 'random'],
                                             'type': 'string'}},
             'required': ['prompt', 'trigger_type', 'timezone'],
             'type': 'object'},
  'skill_id': 'set-reminder',
  'skill_method_py': 'set_reminder',
  'skill_method_ts': 'setReminder'},
 {'app_id': 'reminder',
  'app_namespace_py': 'reminder',
  'app_namespace_ts': 'reminder',
  'description': "Show the user's existing scheduled reminders.",
  'description_key': 'reminder.list_reminders.description',
  'schema': {'properties': {'status': {'default': 'pending',
                                       'description': "Filter reminders by status. 'pending' shows "
                                                      'only upcoming reminders.',
                                       'enum': ['pending', 'all'],
                                       'type': 'string'}},
             'type': 'object'},
  'skill_id': 'list-reminders',
  'skill_method_py': 'list_reminders',
  'skill_method_ts': 'listReminders'},
 {'app_id': 'reminder',
  'app_namespace_py': 'reminder',
  'app_namespace_ts': 'reminder',
  'description': 'Cancel or delete an existing reminder.',
  'description_key': 'reminder.cancel_reminder.description',
  'schema': {'properties': {'reminder_id': {'description': 'ID of the reminder to cancel',
                                            'type': 'string'}},
             'required': ['reminder_id'],
             'type': 'object'},
  'skill_id': 'cancel-reminder',
  'skill_method_py': 'cancel_reminder',
  'skill_method_ts': 'cancelReminder'},
 {'app_id': 'shopping',
  'app_namespace_py': 'shopping',
  'app_namespace_ts': 'shopping',
  'description': 'Search products on REWE, Amazon, or Stoffe.de with real-time prices. Use '
                 'category to route groceries, marketplace products, fabrics, sewing supplies, and '
                 'patterns to compatible providers. Invalid provider/category combinations are '
                 'rejected.',
  'description_key': 'app_skills.shopping.search_products.description',
  'schema': {'properties': {'requests': {'description': 'Array of product search requests. Each '
                                                        'request searches for products matching a '
                                                        'query on a compatible shopping '
                                                        'provider.\n',
                                         'items': {'properties': {'category': {'description': 'Product '
                                                                                              'category '
                                                                                              'used '
                                                                                              'for '
                                                                                              'routing '
                                                                                              'and '
                                                                                              'provider '
                                                                                              'compatibility. '
                                                                                              'Fabrics '
                                                                                              'can '
                                                                                              'be '
                                                                                              'searched '
                                                                                              'on '
                                                                                              'Stoffe.de '
                                                                                              'or '
                                                                                              'Amazon. '
                                                                                              'Groceries '
                                                                                              'can '
                                                                                              'be '
                                                                                              'searched '
                                                                                              'on '
                                                                                              'REWE '
                                                                                              'or '
                                                                                              'Amazon. '
                                                                                              'Marketplace '
                                                                                              'categories '
                                                                                              'are '
                                                                                              'Amazon-only.\n',
                                                                               'enum': ['grocery',
                                                                                        'fabrics',
                                                                                        'sewing_supplies',
                                                                                        'patterns',
                                                                                        'general_marketplace',
                                                                                        'electronics',
                                                                                        'home',
                                                                                        'fashion',
                                                                                        'beauty',
                                                                                        'books',
                                                                                        'sports',
                                                                                        'toys',
                                                                                        'automotive',
                                                                                        'health',
                                                                                        'music',
                                                                                        'movies',
                                                                                        'tools',
                                                                                        'office',
                                                                                        'pet_supplies',
                                                                                        'video_games',
                                                                                        'baby'],
                                                                               'type': 'string'},
                                                                  'country': {'description': 'Amazon-only '
                                                                                             'marketplace '
                                                                                             'country '
                                                                                             'code. '
                                                                                             'Example: '
                                                                                             'us, '
                                                                                             'uk, '
                                                                                             'de, '
                                                                                             'fr, '
                                                                                             'it, '
                                                                                             'es, '
                                                                                             'ca, '
                                                                                             'au, '
                                                                                             'jp, '
                                                                                             'in, '
                                                                                             'br, '
                                                                                             'mx, '
                                                                                             'nl, '
                                                                                             'sg, '
                                                                                             'se, '
                                                                                             'pl. '
                                                                                             'If '
                                                                                             'omitted, '
                                                                                             'inferred '
                                                                                             'from '
                                                                                             'user '
                                                                                             'language/locale '
                                                                                             'with '
                                                                                             'fallback '
                                                                                             'to '
                                                                                             'us.\n',
                                                                              'type': 'string'},
                                                                  'department': {'description': 'Amazon-only '
                                                                                                'category '
                                                                                                'filter. '
                                                                                                'Example: '
                                                                                                'electronics, '
                                                                                                'computers, '
                                                                                                'fashion, '
                                                                                                'home, '
                                                                                                'books, '
                                                                                                'sports, '
                                                                                                'toys, '
                                                                                                'beauty, '
                                                                                                'grocery, '
                                                                                                'automotive, '
                                                                                                'health, '
                                                                                                'music, '
                                                                                                'movies, '
                                                                                                'tools, '
                                                                                                'office, '
                                                                                                'pet_supplies, '
                                                                                                'video_games, '
                                                                                                'baby.\n',
                                                                                 'enum': ['electronics',
                                                                                          'computers',
                                                                                          'fashion',
                                                                                          'home',
                                                                                          'books',
                                                                                          'sports',
                                                                                          'toys',
                                                                                          'beauty',
                                                                                          'grocery',
                                                                                          'automotive',
                                                                                          'health',
                                                                                          'music',
                                                                                          'movies',
                                                                                          'tools',
                                                                                          'office',
                                                                                          'pet_supplies',
                                                                                          'video_games',
                                                                                          'baby'],
                                                                                 'type': 'string'},
                                                                  'max_price': {'description': 'Amazon-only '
                                                                                               'maximum '
                                                                                               'price '
                                                                                               'filter '
                                                                                               '(client-side '
                                                                                               'after '
                                                                                               'fetch).',
                                                                                'type': 'number'},
                                                                  'max_results': {'default': 10,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'products '
                                                                                                 'to '
                                                                                                 'return '
                                                                                                 '(1-20, '
                                                                                                 'default '
                                                                                                 '10).',
                                                                                  'type': 'integer'},
                                                                  'min_price': {'description': 'Amazon-only '
                                                                                               'minimum '
                                                                                               'price '
                                                                                               'filter '
                                                                                               '(client-side '
                                                                                               'after '
                                                                                               'fetch).',
                                                                                'type': 'number'},
                                                                  'provider': {'description': 'Product '
                                                                                              'provider. '
                                                                                              'If '
                                                                                              'omitted, '
                                                                                              'inferred '
                                                                                              'from '
                                                                                              'category: '
                                                                                              'grocery '
                                                                                              'routes '
                                                                                              'to '
                                                                                              'REWE, '
                                                                                              'fabrics/sewing_supplies/patterns '
                                                                                              'route '
                                                                                              'to '
                                                                                              'Stoffe.de, '
                                                                                              'and '
                                                                                              'marketplace '
                                                                                              'categories '
                                                                                              'route '
                                                                                              'to '
                                                                                              'Amazon. '
                                                                                              'Invalid '
                                                                                              'explicit '
                                                                                              'provider/category '
                                                                                              'combinations '
                                                                                              'are '
                                                                                              'rejected.\n',
                                                                               'enum': ['REWE',
                                                                                        'Amazon',
                                                                                        'Stoffe.de'],
                                                                               'type': 'string'},
                                                                  'query': {'description': 'Search '
                                                                                           'query, '
                                                                                           'e.g. '
                                                                                           '"bio '
                                                                                           'joghurt", '
                                                                                           '"coffee '
                                                                                           'grinder", '
                                                                                           '"wireless '
                                                                                           'mouse".\n',
                                                                            'type': 'string'},
                                                                  'service_type': {'default': 'DELIVERY',
                                                                                   'description': 'REWE-only '
                                                                                                  'fulfilment '
                                                                                                  'type. '
                                                                                                  '"DELIVERY" '
                                                                                                  'for '
                                                                                                  'home '
                                                                                                  'delivery '
                                                                                                  '(default). '
                                                                                                  '"CLICK_AND_COLLECT" '
                                                                                                  'for '
                                                                                                  'store '
                                                                                                  'pickup. '
                                                                                                  'Ignored '
                                                                                                  'for '
                                                                                                  'Amazon '
                                                                                                  'and '
                                                                                                  'Stoffe.de.\n',
                                                                                   'enum': ['DELIVERY',
                                                                                            'CLICK_AND_COLLECT'],
                                                                                   'type': 'string'},
                                                                  'sort': {'default': 'relevance',
                                                                           'description': 'Sort '
                                                                                          'order '
                                                                                          'for '
                                                                                          'results. '
                                                                                          'REWE '
                                                                                          'supports: '
                                                                                          'relevance, '
                                                                                          'price_asc, '
                                                                                          'price_desc, '
                                                                                          'new. '
                                                                                          'Amazon '
                                                                                          'supports: '
                                                                                          'relevance, '
                                                                                          'price_asc, '
                                                                                          'price_desc, '
                                                                                          'review_rank, '
                                                                                          'newest, '
                                                                                          'best_sellers. '
                                                                                          'Stoffe.de '
                                                                                          'supports: '
                                                                                          'relevance, '
                                                                                          'price_asc, '
                                                                                          'price_desc, '
                                                                                          'new.\n',
                                                                           'enum': ['relevance',
                                                                                    'price_asc',
                                                                                    'price_desc',
                                                                                    'new',
                                                                                    'review_rank',
                                                                                    'newest',
                                                                                    'best_sellers'],
                                                                           'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_products',
  'skill_method_py': 'search_products',
  'skill_method_ts': 'searchProducts'},
 {'app_id': 'social_media',
  'app_namespace_py': 'social_media',
  'app_namespace_ts': 'socialMedia',
  'description': 'Fetch recent social media posts from one or more specific platform pages or '
                 'profiles. Supports Reddit subreddits, Bluesky profile feeds, and Mastodon public '
                 'profiles. Use for profile monitoring, community research, and finding '
                 'conversations to review manually. Costs 10 credits per request.',
  'description_key': 'app_skills.social_media.get_posts.description',
  'schema': {'properties': {'requests': {'description': 'Array of social post fetch requests. For '
                                                        'Reddit, page is the subreddit name '
                                                        'without r/ (for example: privacy, '
                                                        'selfhosted, buildinpublic). For Bluesky '
                                                        'profile posts, page is the actor handle. '
                                                        'For Mastodon, page is user@instance or a '
                                                        'public profile URL.\n',
                                         'items': {'properties': {'comments_limit': {'default': 5,
                                                                                     'description': 'Number '
                                                                                                    'of '
                                                                                                    'comments/replies '
                                                                                                    'to '
                                                                                                    'fetch '
                                                                                                    'per '
                                                                                                    'post.',
                                                                                     'maximum': 5,
                                                                                     'minimum': 0,
                                                                                     'type': 'integer'},
                                                                  'comments_sort': {'default': 'top',
                                                                                    'description': 'Reddit '
                                                                                                   'comment '
                                                                                                   'sort. '
                                                                                                   'Bluesky '
                                                                                                   'and '
                                                                                                   'Mastodon '
                                                                                                   'ignore '
                                                                                                   'this '
                                                                                                   'value.',
                                                                                    'enum': ['confidence',
                                                                                             'top',
                                                                                             'new',
                                                                                             'controversial',
                                                                                             'old'],
                                                                                    'type': 'string'},
                                                                  'exclude_nsfw': {'default': True,
                                                                                   'description': 'Exclude '
                                                                                                  'NSFW '
                                                                                                  'Reddit '
                                                                                                  'posts.',
                                                                                   'type': 'boolean'},
                                                                  'exclude_stickied': {'default': True,
                                                                                       'description': 'Exclude '
                                                                                                      'stickied '
                                                                                                      'Reddit '
                                                                                                      'posts.',
                                                                                       'type': 'boolean'},
                                                                  'id': {'description': 'Optional '
                                                                                        'caller-supplied '
                                                                                        'ID for '
                                                                                        'correlating '
                                                                                        'responses.'},
                                                                  'include_comments': {'default': True,
                                                                                       'description': 'Whether '
                                                                                                      'to '
                                                                                                      'fetch '
                                                                                                      'comments/replies '
                                                                                                      'for '
                                                                                                      'returned '
                                                                                                      'posts '
                                                                                                      'when '
                                                                                                      'supported.',
                                                                                       'type': 'boolean'},
                                                                  'include_link_posts': {'default': True,
                                                                                         'description': 'Include '
                                                                                                        'Reddit '
                                                                                                        'link/media '
                                                                                                        'posts.',
                                                                                         'type': 'boolean'},
                                                                  'include_self_posts': {'default': True,
                                                                                         'description': 'Include '
                                                                                                        'Reddit '
                                                                                                        'text/self '
                                                                                                        'posts.',
                                                                                         'type': 'boolean'},
                                                                  'limit': {'default': 10,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'posts '
                                                                                           'to '
                                                                                           'fetch '
                                                                                           'per '
                                                                                           'page.',
                                                                            'maximum': 25,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'min_comments': {'description': 'Minimum '
                                                                                                  'Reddit '
                                                                                                  'comment '
                                                                                                  'count '
                                                                                                  'to '
                                                                                                  'include.',
                                                                                   'minimum': 0,
                                                                                   'type': 'integer'},
                                                                  'min_score': {'description': 'Minimum '
                                                                                               'Reddit '
                                                                                               'score/upvotes '
                                                                                               'to '
                                                                                               'include.',
                                                                                'minimum': 0,
                                                                                'type': 'integer'},
                                                                  'page': {'description': 'Platform '
                                                                                          'page/profile '
                                                                                          'identifier. '
                                                                                          'For '
                                                                                          'Reddit, '
                                                                                          'this is '
                                                                                          'the '
                                                                                          'subreddit '
                                                                                          'name. '
                                                                                          'For '
                                                                                          'Bluesky, '
                                                                                          'this is '
                                                                                          'an '
                                                                                          'actor '
                                                                                          'handle '
                                                                                          'for '
                                                                                          'profile '
                                                                                          'feeds. '
                                                                                          'For '
                                                                                          'Mastodon, '
                                                                                          'use '
                                                                                          'user@instance '
                                                                                          'or a '
                                                                                          'profile '
                                                                                          'URL.',
                                                                           'type': 'string'},
                                                                  'platform': {'default': 'reddit',
                                                                               'description': 'Social '
                                                                                              'platform '
                                                                                              'to '
                                                                                              'fetch '
                                                                                              'from.',
                                                                               'enum': ['bluesky',
                                                                                        'mastodon',
                                                                                        'reddit'],
                                                                               'type': 'string'},
                                                                  'sort': {'default': 'new',
                                                                           'description': 'Post '
                                                                                          'listing '
                                                                                          'sort. '
                                                                                          'Reddit '
                                                                                          'supports '
                                                                                          'new/hot/rising/top/comments. '
                                                                                          'Comments '
                                                                                          'means '
                                                                                          'most '
                                                                                          'discussed '
                                                                                          'in the '
                                                                                          'selected '
                                                                                          'time '
                                                                                          'range. '
                                                                                          'Bluesky '
                                                                                          'and '
                                                                                          'Mastodon '
                                                                                          'profile '
                                                                                          'feeds '
                                                                                          'ignore '
                                                                                          'this '
                                                                                          'value.',
                                                                           'enum': ['new',
                                                                                    'hot',
                                                                                    'rising',
                                                                                    'top',
                                                                                    'comments'],
                                                                           'type': 'string'},
                                                                  'time_range': {'description': 'Reddit '
                                                                                                'time '
                                                                                                'filter '
                                                                                                'for '
                                                                                                'top/comments '
                                                                                                'sorts.',
                                                                                 'enum': ['hour',
                                                                                          'day',
                                                                                          'week',
                                                                                          'month',
                                                                                          'year',
                                                                                          'all'],
                                                                                 'type': 'string'}},
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'get-posts',
  'skill_method_py': 'get_posts',
  'skill_method_ts': 'getPosts'},
 {'app_id': 'social_media',
  'app_namespace_py': 'social_media',
  'app_namespace_ts': 'socialMedia',
  'description': 'Search supported social platforms for recent public posts around a topic. Use '
                 'this for topic monitoring and broad discovery across pages/profiles, not for '
                 'monitoring a known profile; use Get posts for profile/page posts. Omit platform '
                 'to search every supported social platform. Costs 10 credits per request.',
  'description_key': 'app_skills.social_media.search.description',
  'schema': {'properties': {'requests': {'description': 'Array of social post search requests. For '
                                                        'Bluesky, query is the topic to search and '
                                                        'author optionally restricts results to a '
                                                        'specific handle. For Mastodon, '
                                                        'mastodon.social is searched by default '
                                                        'and mastodon_instances can add more '
                                                        'public instances.\n',
                                         'items': {'properties': {'author': {'description': 'Optional '
                                                                                            'platform '
                                                                                            'profile/handle '
                                                                                            'filter. '
                                                                                            'For '
                                                                                            'Bluesky, '
                                                                                            'this '
                                                                                            'maps '
                                                                                            'to '
                                                                                            'the '
                                                                                            'author '
                                                                                            'filter.',
                                                                             'type': 'string'},
                                                                  'comments_limit': {'default': 0,
                                                                                     'description': 'Number '
                                                                                                    'of '
                                                                                                    'comments/replies '
                                                                                                    'to '
                                                                                                    'fetch '
                                                                                                    'per '
                                                                                                    'returned '
                                                                                                    'post '
                                                                                                    'when '
                                                                                                    'supported.',
                                                                                     'maximum': 5,
                                                                                     'minimum': 0,
                                                                                     'type': 'integer'},
                                                                  'comments_sort': {'default': 'top',
                                                                                    'description': 'Reddit '
                                                                                                   'comment '
                                                                                                   'sort.',
                                                                                    'enum': ['confidence',
                                                                                             'top',
                                                                                             'new',
                                                                                             'controversial',
                                                                                             'old'],
                                                                                    'type': 'string'},
                                                                  'exclude_nsfw': {'default': True,
                                                                                   'description': 'Exclude '
                                                                                                  'NSFW '
                                                                                                  'Reddit '
                                                                                                  'posts.',
                                                                                   'type': 'boolean'},
                                                                  'exclude_stickied': {'default': True,
                                                                                       'description': 'Exclude '
                                                                                                      'stickied '
                                                                                                      'Reddit '
                                                                                                      'posts.',
                                                                                       'type': 'boolean'},
                                                                  'id': {'description': 'Optional '
                                                                                        'caller-supplied '
                                                                                        'ID for '
                                                                                        'correlating '
                                                                                        'responses.'},
                                                                  'include_comments': {'default': False,
                                                                                       'description': 'Whether '
                                                                                                      'to '
                                                                                                      'fetch '
                                                                                                      'comments/replies '
                                                                                                      'for '
                                                                                                      'returned '
                                                                                                      'posts '
                                                                                                      'when '
                                                                                                      'supported.',
                                                                                       'type': 'boolean'},
                                                                  'limit': {'default': 10,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'posts '
                                                                                           'to '
                                                                                           'fetch '
                                                                                           'per '
                                                                                           'search.',
                                                                            'maximum': 25,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'mastodon_instances': {'description': 'Optional '
                                                                                                        'additional '
                                                                                                        'Mastodon '
                                                                                                        'instances '
                                                                                                        'to '
                                                                                                        'search '
                                                                                                        'after '
                                                                                                        'mastodon.social, '
                                                                                                        'for '
                                                                                                        'example '
                                                                                                        'fosstodon.org '
                                                                                                        'or '
                                                                                                        'hachyderm.io.',
                                                                                         'items': {'type': 'string'},
                                                                                         'type': 'array'},
                                                                  'min_comments': {'description': 'Minimum '
                                                                                                  'Reddit '
                                                                                                  'comment '
                                                                                                  'count '
                                                                                                  'to '
                                                                                                  'include.',
                                                                                   'minimum': 0,
                                                                                   'type': 'integer'},
                                                                  'min_score': {'description': 'Minimum '
                                                                                               'Reddit '
                                                                                               'score/upvotes '
                                                                                               'to '
                                                                                               'include.',
                                                                                'minimum': 0,
                                                                                'type': 'integer'},
                                                                  'page': {'description': 'Optional '
                                                                                          'subreddit/page '
                                                                                          'to '
                                                                                          'restrict '
                                                                                          'Reddit '
                                                                                          'search '
                                                                                          'to, '
                                                                                          'without '
                                                                                          'r/. For '
                                                                                          'Mastodon, '
                                                                                          'optionally '
                                                                                          'provide '
                                                                                          'one '
                                                                                          'extra '
                                                                                          'instance '
                                                                                          'such as '
                                                                                          'fosstodon.org.',
                                                                           'type': 'string'},
                                                                  'platform': {'default': 'all',
                                                                               'description': 'Social '
                                                                                              'platform '
                                                                                              'to '
                                                                                              'search. '
                                                                                              'Omit '
                                                                                              'or '
                                                                                              'use '
                                                                                              'all '
                                                                                              'to '
                                                                                              'search '
                                                                                              'every '
                                                                                              'supported '
                                                                                              'provider.',
                                                                               'enum': ['all',
                                                                                        'bluesky',
                                                                                        'mastodon',
                                                                                        'reddit'],
                                                                               'type': 'string'},
                                                                  'query': {'description': 'Topic '
                                                                                           'or '
                                                                                           'search '
                                                                                           'query '
                                                                                           'to '
                                                                                           'find '
                                                                                           'posts '
                                                                                           'around.',
                                                                            'type': 'string'},
                                                                  'sort': {'default': 'latest',
                                                                           'description': 'Search '
                                                                                          'sort. '
                                                                                          'Bluesky '
                                                                                          'supports '
                                                                                          'latest/top. '
                                                                                          'Reddit '
                                                                                          'supports '
                                                                                          'relevance/hot/top/new/comments/latest. '
                                                                                          'Mastodon '
                                                                                          'public '
                                                                                          'search '
                                                                                          'returns '
                                                                                          'instance-ranked '
                                                                                          'recent '
                                                                                          'results '
                                                                                          'and '
                                                                                          'ignores '
                                                                                          'sort.',
                                                                           'enum': ['latest',
                                                                                    'top',
                                                                                    'new',
                                                                                    'hot',
                                                                                    'relevance',
                                                                                    'comments'],
                                                                           'type': 'string'},
                                                                  'time_range': {'description': 'Reddit '
                                                                                                'time '
                                                                                                'filter '
                                                                                                'for '
                                                                                                'top/comments '
                                                                                                'search.',
                                                                                 'enum': ['hour',
                                                                                          'day',
                                                                                          'week',
                                                                                          'month',
                                                                                          'year',
                                                                                          'all'],
                                                                                 'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'tasks',
  'app_namespace_py': 'tasks',
  'app_namespace_ts': 'tasks',
  'description': 'Create one or more user-visible tasks. Use this for planning, task capture, or '
                 'breaking a request into trackable work. Default unclear assignees to the user.',
  'description_key': 'tasks.skills.create.description',
  'schema': {'properties': {'assignee': {'enum': ['user', 'openmates'], 'type': 'string'},
                            'description': {'type': 'string'},
                            'tasks': {'items': {'properties': {'assignee': {'enum': ['user',
                                                                                     'openmates'],
                                                                            'type': 'string'},
                                                               'description': {'type': 'string'},
                                                               'status': {'enum': ['backlog',
                                                                                   'todo',
                                                                                   'in_progress',
                                                                                   'blocked'],
                                                                          'type': 'string'},
                                                               'title': {'type': 'string'}},
                                                'type': 'object'},
                                      'type': 'array'},
                            'title': {'description': 'Single-task title when not using tasks[].',
                                      'type': 'string'}},
             'required': [],
             'type': 'object'},
  'skill_id': 'create',
  'skill_method_py': 'create',
  'skill_method_ts': 'create'},
 {'app_id': 'tasks',
  'app_namespace_py': 'tasks',
  'app_namespace_ts': 'tasks',
  'description': "Search the user's encrypted tasks through a connected capable client. Do not use "
                 'server-visible metadata as a private task-content search fallback.',
  'description_key': 'tasks.skills.search.description',
  'schema': {'properties': {'query': {'description': 'Private task text to search for on a '
                                                     'connected client.',
                                      'type': 'string'}},
             'required': ['query'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'travel',
  'app_namespace_py': 'travel',
  'app_namespace_ts': 'travel',
  'description': 'Search for flight or train connections for a particular date with details '
                 '(airlines/operators, times, stops, durations, prices). Use when user asks about '
                 'flights, train connections, or travel between cities on a specific date. Set '
                 'transport_methods to ["airplane"] for flights or ["train"] for trains. If the '
                 'user names a provider, set providers to one or more of: google_flights, '
                 'deutsche_bahn, flix. If no provider is specified, all providers for the selected '
                 'transport method are searched. Add cou',
  'description_key': 'app_skills.travel.search_connections.description',
  'schema': {'properties': {'requests': {'description': 'Array of connection search requests. Each '
                                                        'request searches for transport '
                                                        'connections for a complete trip (one-way, '
                                                        'round trip, or multi-stop).\n',
                                         'items': {'properties': {'avoid_overnight_layovers': {'default': False,
                                                                                               'description': 'If '
                                                                                                              'true, '
                                                                                                              'remove '
                                                                                                              'connections '
                                                                                                              'with '
                                                                                                              'overnight '
                                                                                                              'layovers '
                                                                                                              'or '
                                                                                                              'transfers.',
                                                                                               'type': 'boolean'},
                                                                  'countries': {'description': 'ISO '
                                                                                               '3166-1 '
                                                                                               'alpha-2 '
                                                                                               'country '
                                                                                               'codes '
                                                                                               'involved '
                                                                                               'in '
                                                                                               'the '
                                                                                               'route, '
                                                                                               'inferred '
                                                                                               'from '
                                                                                               'origin, '
                                                                                               'destination, '
                                                                                               'and '
                                                                                               'known '
                                                                                               'stops. '
                                                                                               'Country '
                                                                                               'matching '
                                                                                               'is '
                                                                                               'OR: '
                                                                                               'a '
                                                                                               'provider '
                                                                                               'is '
                                                                                               'relevant '
                                                                                               'when '
                                                                                               'it '
                                                                                               'supports '
                                                                                               'at '
                                                                                               'least '
                                                                                               'one '
                                                                                               'listed '
                                                                                               'country. '
                                                                                               'Google '
                                                                                               'Flights '
                                                                                               'is '
                                                                                               'global '
                                                                                               'and '
                                                                                               'remains '
                                                                                               'eligible '
                                                                                               'for '
                                                                                               'airplane '
                                                                                               'searches '
                                                                                               'in '
                                                                                               'all '
                                                                                               'countries.\n',
                                                                                'items': {'type': 'string'},
                                                                                'type': 'array'},
                                                                  'currency': {'default': 'EUR',
                                                                               'description': 'Preferred '
                                                                                              'currency '
                                                                                              'for '
                                                                                              'prices '
                                                                                              '(ISO '
                                                                                              '4217 '
                                                                                              'code).',
                                                                               'type': 'string'},
                                                                  'exclude_airlines': {'description': 'Exclude '
                                                                                                      'flights '
                                                                                                      'from '
                                                                                                      'these '
                                                                                                      'airlines. '
                                                                                                      'Use '
                                                                                                      'IATA '
                                                                                                      'carrier '
                                                                                                      'codes '
                                                                                                      'when '
                                                                                                      'known. '
                                                                                                      'Do '
                                                                                                      'not '
                                                                                                      'combine '
                                                                                                      'with '
                                                                                                      'include_airlines.',
                                                                                       'items': {'type': 'string'},
                                                                                       'type': 'array'},
                                                                  'include_airlines': {'description': 'Only '
                                                                                                      'show '
                                                                                                      'flights '
                                                                                                      'from '
                                                                                                      'these '
                                                                                                      'airlines. '
                                                                                                      'Use '
                                                                                                      'IATA '
                                                                                                      'carrier '
                                                                                                      'codes '
                                                                                                      'when '
                                                                                                      'known, '
                                                                                                      'such '
                                                                                                      'as '
                                                                                                      'LH, '
                                                                                                      'BA, '
                                                                                                      'VY, '
                                                                                                      'or '
                                                                                                      'FR.',
                                                                                       'items': {'type': 'string'},
                                                                                       'type': 'array'},
                                                                  'legs': {'description': 'Ordered '
                                                                                          'list of '
                                                                                          'trip '
                                                                                          'legs. '
                                                                                          'One-way '
                                                                                          'trip = '
                                                                                          '1 leg. '
                                                                                          'Round '
                                                                                          'trip = '
                                                                                          '2 legs '
                                                                                          '(outbound '
                                                                                          '+ '
                                                                                          'return). '
                                                                                          'Multi-stop '
                                                                                          '= N '
                                                                                          'legs. '
                                                                                          'Each '
                                                                                          'leg '
                                                                                          'specifies '
                                                                                          'an '
                                                                                          'origin, '
                                                                                          'destination, '
                                                                                          'and '
                                                                                          'departure '
                                                                                          'date.\n',
                                                                           'items': {'properties': {'date': {'description': 'Departure '
                                                                                                                            'date '
                                                                                                                            'in '
                                                                                                                            'YYYY-MM-DD '
                                                                                                                            'format.',
                                                                                                             'type': 'string'},
                                                                                                    'destination': {'description': 'Destination '
                                                                                                                                   'city '
                                                                                                                                   'or '
                                                                                                                                   'location '
                                                                                                                                   'name.',
                                                                                                                    'type': 'string'},
                                                                                                    'origin': {'description': 'Origin '
                                                                                                                              'city '
                                                                                                                              'or '
                                                                                                                              'location '
                                                                                                                              'name '
                                                                                                                              '(e.g. '
                                                                                                                              '"Munich", '
                                                                                                                              '"London '
                                                                                                                              'Heathrow", '
                                                                                                                              '"Berlin"). '
                                                                                                                              'The '
                                                                                                                              'system '
                                                                                                                              'resolves '
                                                                                                                              'this '
                                                                                                                              'to '
                                                                                                                              'airport '
                                                                                                                              'codes '
                                                                                                                              'or '
                                                                                                                              'coordinates '
                                                                                                                              'internally.\n',
                                                                                                               'type': 'string'}},
                                                                                     'required': ['origin',
                                                                                                  'destination',
                                                                                                  'date'],
                                                                                     'type': 'object'},
                                                                           'type': 'array'},
                                                                  'max_arrival_time': {'description': 'Latest '
                                                                                                      'acceptable '
                                                                                                      'local '
                                                                                                      'arrival '
                                                                                                      'time '
                                                                                                      'in '
                                                                                                      'HH:MM '
                                                                                                      'format.',
                                                                                       'type': 'string'},
                                                                  'max_departure_time': {'description': 'Latest '
                                                                                                        'acceptable '
                                                                                                        'local '
                                                                                                        'departure '
                                                                                                        'time '
                                                                                                        'in '
                                                                                                        'HH:MM '
                                                                                                        'format.',
                                                                                         'type': 'string'},
                                                                  'max_duration_minutes': {'description': 'Maximum '
                                                                                                          'total '
                                                                                                          'duration '
                                                                                                          'for '
                                                                                                          'the '
                                                                                                          'first '
                                                                                                          'leg, '
                                                                                                          'in '
                                                                                                          'minutes.',
                                                                                           'type': 'integer'},
                                                                  'max_layover_minutes': {'description': 'Maximum '
                                                                                                         'allowed '
                                                                                                         'layover '
                                                                                                         'or '
                                                                                                         'transfer '
                                                                                                         'duration, '
                                                                                                         'in '
                                                                                                         'minutes.',
                                                                                          'type': 'integer'},
                                                                  'max_price': {'description': 'Maximum '
                                                                                               'total '
                                                                                               'price '
                                                                                               'for '
                                                                                               'the '
                                                                                               'connection '
                                                                                               'in '
                                                                                               'the '
                                                                                               'requested '
                                                                                               'currency. '
                                                                                               'Results '
                                                                                               'above '
                                                                                               'this '
                                                                                               'price '
                                                                                               'are '
                                                                                               'filtered '
                                                                                               'from '
                                                                                               'strict '
                                                                                               'matches.',
                                                                                'type': 'number'},
                                                                  'max_results': {'default': 6,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'connection '
                                                                                                 'options '
                                                                                                 'to '
                                                                                                 'return '
                                                                                                 'per '
                                                                                                 'transport '
                                                                                                 'method.',
                                                                                  'type': 'integer'},
                                                                  'max_stops': {'description': 'Maximum '
                                                                                               'number '
                                                                                               'of '
                                                                                               'stops '
                                                                                               'allowed. '
                                                                                               'Use '
                                                                                               '0 '
                                                                                               'for '
                                                                                               'direct/non-stop '
                                                                                               'only, '
                                                                                               '1 '
                                                                                               'for '
                                                                                               'up '
                                                                                               'to '
                                                                                               'one '
                                                                                               'stop, '
                                                                                               'or '
                                                                                               '2 '
                                                                                               'for '
                                                                                               'up '
                                                                                               'to '
                                                                                               'two '
                                                                                               'stops.',
                                                                                'type': 'integer'},
                                                                  'min_arrival_time': {'description': 'Earliest '
                                                                                                      'acceptable '
                                                                                                      'local '
                                                                                                      'arrival '
                                                                                                      'time '
                                                                                                      'in '
                                                                                                      'HH:MM '
                                                                                                      'format.',
                                                                                       'type': 'string'},
                                                                  'min_departure_time': {'description': 'Earliest '
                                                                                                        'acceptable '
                                                                                                        'local '
                                                                                                        'departure '
                                                                                                        'time '
                                                                                                        'in '
                                                                                                        'HH:MM '
                                                                                                        'format.',
                                                                                         'type': 'string'},
                                                                  'non_stop_only': {'default': False,
                                                                                    'description': 'If '
                                                                                                   'true, '
                                                                                                   'only '
                                                                                                   'return '
                                                                                                   'direct/non-stop '
                                                                                                   'connections.',
                                                                                    'type': 'boolean'},
                                                                  'passengers': {'default': 1,
                                                                                 'description': 'Number '
                                                                                                'of '
                                                                                                'adult '
                                                                                                'passengers.',
                                                                                 'type': 'integer'},
                                                                  'providers': {'description': 'Optional '
                                                                                               'provider '
                                                                                               'IDs '
                                                                                               'to '
                                                                                               'search. '
                                                                                               'Use '
                                                                                               '"google_flights" '
                                                                                               'for '
                                                                                               'flights, '
                                                                                               '"deutsche_bahn" '
                                                                                               'for '
                                                                                               'Deutsche '
                                                                                               'Bahn '
                                                                                               '/ '
                                                                                               'ICE '
                                                                                               '/ '
                                                                                               'Bahn.de '
                                                                                               '/ '
                                                                                               'Sparpreis '
                                                                                               'train '
                                                                                               'searches, '
                                                                                               'and '
                                                                                               '"flix" '
                                                                                               'for '
                                                                                               'FlixBus '
                                                                                               '/ '
                                                                                               'FlixTrain. '
                                                                                               'If '
                                                                                               'omitted, '
                                                                                               'all '
                                                                                               'providers '
                                                                                               'for '
                                                                                               'the '
                                                                                               'selected '
                                                                                               'transport '
                                                                                               'method '
                                                                                               'are '
                                                                                               'used, '
                                                                                               'then '
                                                                                               'filtered '
                                                                                               'by '
                                                                                               'countries '
                                                                                               'if '
                                                                                               'provided.\n',
                                                                                'items': {'enum': ['google_flights',
                                                                                                   'deutsche_bahn',
                                                                                                   'flix'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                                  'sort_by': {'default': 'price_asc',
                                                                              'description': 'How '
                                                                                             'to '
                                                                                             'sort '
                                                                                             'the '
                                                                                             'results. '
                                                                                             'Options: '
                                                                                             '"price_asc" '
                                                                                             '(cheapest '
                                                                                             'first, '
                                                                                             'default), '
                                                                                             '"price_desc" '
                                                                                             '(most '
                                                                                             'expensive '
                                                                                             'first), '
                                                                                             '"duration_asc" '
                                                                                             '(shortest '
                                                                                             'first), '
                                                                                             '"duration_desc" '
                                                                                             '(longest '
                                                                                             'first), '
                                                                                             '"departure_asc" '
                                                                                             '(earliest '
                                                                                             'departure '
                                                                                             'first), '
                                                                                             '"departure_desc" '
                                                                                             '(latest '
                                                                                             'departure '
                                                                                             'first), '
                                                                                             '"stops_asc" '
                                                                                             '(fewest '
                                                                                             'stops '
                                                                                             'first), '
                                                                                             '"stops_desc" '
                                                                                             '(most '
                                                                                             'stops '
                                                                                             'first).\n',
                                                                              'enum': ['price_asc',
                                                                                       'price_desc',
                                                                                       'duration_asc',
                                                                                       'duration_desc',
                                                                                       'departure_asc',
                                                                                       'departure_desc',
                                                                                       'stops_asc',
                                                                                       'stops_desc'],
                                                                              'type': 'string'},
                                                                  'transport_methods': {'default': ['airplane'],
                                                                                        'description': 'Transport '
                                                                                                       'types '
                                                                                                       'to '
                                                                                                       'search. '
                                                                                                       'Supported: '
                                                                                                       '"airplane" '
                                                                                                       '(worldwide '
                                                                                                       'via '
                                                                                                       'Google '
                                                                                                       'Flights), '
                                                                                                       '"train" '
                                                                                                       '(Germany '
                                                                                                       '+ '
                                                                                                       'select '
                                                                                                       'European '
                                                                                                       'routes '
                                                                                                       'via '
                                                                                                       'Deutsche '
                                                                                                       'Bahn '
                                                                                                       'and '
                                                                                                       'FlixTrain). '
                                                                                                       'IMPORTANT: '
                                                                                                       'Set '
                                                                                                       'to '
                                                                                                       '["train"] '
                                                                                                       'when '
                                                                                                       'user '
                                                                                                       'asks '
                                                                                                       'about '
                                                                                                       'trains, '
                                                                                                       'rail, '
                                                                                                       'or '
                                                                                                       'Deutsche '
                                                                                                       'Bahn.\n',
                                                                                        'items': {'enum': ['airplane',
                                                                                                           'train',
                                                                                                           'bus',
                                                                                                           'boat'],
                                                                                                  'type': 'string'},
                                                                                        'type': 'array'},
                                                                  'travel_class': {'default': 'economy',
                                                                                   'description': 'Cabin '
                                                                                                  'class '
                                                                                                  'for '
                                                                                                  'flights.',
                                                                                   'enum': ['economy',
                                                                                            'premium_economy',
                                                                                            'business',
                                                                                            'first'],
                                                                                   'type': 'string'}},
                                                   'required': ['legs'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_connections',
  'skill_method_py': 'search_connections',
  'skill_method_ts': 'searchConnections'},
 {'app_id': 'travel',
  'app_namespace_py': 'travel',
  'app_namespace_ts': 'travel',
  'description': 'Run this OpenMates app skill.',
  'description_key': 'app_skills.travel.search_stays.description',
  'schema': {'properties': {'requests': {'description': 'Array of stay search requests. Each '
                                                        'request searches for accommodation at a '
                                                        'specific destination for given dates.\n',
                                         'items': {'properties': {'adults': {'default': 2,
                                                                             'description': 'Number '
                                                                                            'of '
                                                                                            'adult '
                                                                                            'guests.',
                                                                             'type': 'integer'},
                                                                  'check_in_date': {'description': 'Check-in '
                                                                                                   'date '
                                                                                                   'in '
                                                                                                   'YYYY-MM-DD '
                                                                                                   'format '
                                                                                                   '(e.g. '
                                                                                                   '"2026-03-15").\n',
                                                                                    'type': 'string'},
                                                                  'check_out_date': {'description': 'Check-out '
                                                                                                    'date '
                                                                                                    'in '
                                                                                                    'YYYY-MM-DD '
                                                                                                    'format '
                                                                                                    '(e.g. '
                                                                                                    '"2026-03-18").\n',
                                                                                     'type': 'string'},
                                                                  'children': {'default': 0,
                                                                               'description': 'Number '
                                                                                              'of '
                                                                                              'children.',
                                                                               'type': 'integer'},
                                                                  'currency': {'default': 'EUR',
                                                                               'description': 'Price '
                                                                                              'currency '
                                                                                              '(ISO '
                                                                                              '4217 '
                                                                                              'code, '
                                                                                              'e.g. '
                                                                                              '"EUR", '
                                                                                              '"USD").\n',
                                                                               'type': 'string'},
                                                                  'hotel_class': {'description': 'Comma-separated '
                                                                                                 'star '
                                                                                                 'rating '
                                                                                                 'filter '
                                                                                                 '(e.g. '
                                                                                                 '"3,4,5" '
                                                                                                 'for '
                                                                                                 '3-star '
                                                                                                 'and '
                                                                                                 'above).\n',
                                                                                  'type': 'string'},
                                                                  'max_price': {'description': 'Maximum '
                                                                                               'nightly '
                                                                                               'price '
                                                                                               'filter.',
                                                                                'type': 'number'},
                                                                  'max_results': {'default': 10,
                                                                                  'description': 'Maximum '
                                                                                                 'number '
                                                                                                 'of '
                                                                                                 'results '
                                                                                                 'to '
                                                                                                 'return.',
                                                                                  'type': 'integer'},
                                                                  'min_price': {'description': 'Minimum '
                                                                                               'nightly '
                                                                                               'price '
                                                                                               'filter.',
                                                                                'type': 'number'},
                                                                  'query': {'description': 'Search '
                                                                                           'query '
                                                                                           'describing '
                                                                                           'the '
                                                                                           'destination '
                                                                                           'or '
                                                                                           'property '
                                                                                           '(e.g. '
                                                                                           '"Hotels '
                                                                                           'in '
                                                                                           'Paris", '
                                                                                           '"Hostels '
                                                                                           'near '
                                                                                           'Eiffel '
                                                                                           'Tower", '
                                                                                           '"Barcelona '
                                                                                           'beachfront '
                                                                                           'hotel").\n',
                                                                            'type': 'string'},
                                                                  'sort_by': {'default': 'relevance',
                                                                              'description': 'Sort '
                                                                                             'order '
                                                                                             'for '
                                                                                             'results. '
                                                                                             'Options: '
                                                                                             '"relevance" '
                                                                                             '(default), '
                                                                                             '"price_asc" '
                                                                                             '(lowest '
                                                                                             'price '
                                                                                             'first), '
                                                                                             '"rating_desc" '
                                                                                             '(highest '
                                                                                             'rated '
                                                                                             'first), '
                                                                                             '"reviews_desc" '
                                                                                             '(most '
                                                                                             'reviewed).\n',
                                                                              'type': 'string'}},
                                                   'required': ['query',
                                                                'check_in_date',
                                                                'check_out_date'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search_stays',
  'skill_method_py': 'search_stays',
  'skill_method_ts': 'searchStays'},
 {'app_id': 'travel',
  'app_namespace_py': 'travel',
  'app_namespace_ts': 'travel',
  'description': 'Fetch the real GPS flight track and actual departure/landing times for a '
                 'specific completed/past flight. Use when the user asks to see how a flight '
                 'actually went, the real flight path on a map, or actual timing and runway info. '
                 "Requires the IATA flight number (e.g. 'LH2472') and the departure date. Costs 7 "
                 'credits per lookup.',
  'description_key': 'app_skills.travel.get_flight.description',
  'schema': {'properties': {'departure_date': {'description': 'Departure date in YYYY-MM-DD format '
                                                              "(e.g. '2026-03-05'). Must be a "
                                                              'past/completed date — live tracking '
                                                              'is not supported.\n',
                                               'type': 'string'},
                            'destination_iata': {'description': 'Optional IATA code of the '
                                                                "destination airport (e.g. 'LHR'). "
                                                                'Used for diversion detection.\n',
                                                 'type': 'string'},
                            'flight_number': {'description': 'IATA flight number including the '
                                                             "carrier code prefix (e.g. 'LH2472', "
                                                             "'BA234', 'AF447'). Do NOT include "
                                                             'spaces.\n',
                                              'type': 'string'},
                            'origin_iata': {'description': 'Optional IATA code of the departure '
                                                           "airport (e.g. 'MUC'). Used for "
                                                           'disambiguation when a flight number '
                                                           'has multiple legs.\n',
                                            'type': 'string'}},
             'required': ['flight_number', 'departure_date'],
             'type': 'object'},
  'skill_id': 'get_flight',
  'skill_method_py': 'get_flight',
  'skill_method_ts': 'getFlight'},
 {'app_id': 'videos',
  'app_namespace_py': 'videos',
  'app_namespace_ts': 'videos',
  'description': 'Generate short photorealistic or generative footage from text prompts using '
                 'Google Veo. Use this when the user asks for cinematic footage, realistic scenes, '
                 'camera movement, stylized animation, or non-deterministic video generation. Do '
                 'not use this for exact text slides, product announcements, diagrams, charts, '
                 'UI-like motion graphics, or branded videos where exact text and layout matter; '
                 'those requests should use videos.create with an explicit ```remotion:Name.tsx '
                 'fence instead. Do not use this',
  'description_key': 'app_skills.videos.generate.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED array of video generation '
                                                        'request objects.',
                                         'items': {'properties': {'aspect_ratio': {'default': '16:9',
                                                                                   'enum': ['16:9',
                                                                                            '9:16'],
                                                                                   'type': 'string'},
                                                                  'duration_seconds': {'default': 8,
                                                                                       'enum': [4,
                                                                                                6,
                                                                                                8],
                                                                                       'type': 'integer'},
                                                                  'model': {'default': 'veo-3.1-generate-preview',
                                                                            'enum': ['veo-3.1-generate-preview',
                                                                                     'veo-3.1-fast-generate-preview',
                                                                                     'veo-3.0-generate-001'],
                                                                            'type': 'string'},
                                                                  'prompt': {'description': 'Detailed '
                                                                                            'text '
                                                                                            'description '
                                                                                            'of '
                                                                                            'the '
                                                                                            'video '
                                                                                            'to '
                                                                                            'generate.',
                                                                             'type': 'string'},
                                                                  'resolution': {'default': '720p',
                                                                                 'enum': ['720p',
                                                                                          '1080p',
                                                                                          '4k'],
                                                                                 'type': 'string'},
                                                                  'seed': {'description': 'Optional '
                                                                                          'seed '
                                                                                          'for '
                                                                                          'more '
                                                                                          'reproducible '
                                                                                          'output '
                                                                                          'when '
                                                                                          'supported.',
                                                                           'type': 'integer'}},
                                                   'required': ['prompt'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'generate',
  'skill_method_py': 'generate',
  'skill_method_ts': 'generate'},
 {'app_id': 'videos',
  'app_namespace_py': 'videos',
  'app_namespace_ts': 'videos',
  'description': 'Create deterministic code-backed videos with Remotion. Use this for text slides, '
                 'product announcements, diagrams, charts, UI-like motion graphics, or branded '
                 'videos where exact text and layout matter. The assistant must write an explicit '
                 '```remotion:Name.tsx fence; do not use this for photorealistic footage or '
                 'generic TSX components.',
  'description_key': 'app_skills.videos.create.description',
  'schema': {'properties': {'filename': {'description': 'Source filename, for example '
                                                        'ProductAnnouncement.tsx.',
                                         'type': 'string'},
                            'source': {'description': 'Remotion TSX source code to render.',
                                       'type': 'string'}},
             'required': ['source'],
             'type': 'object'},
  'skill_id': 'create',
  'skill_method_py': 'create',
  'skill_method_ts': 'create'},
 {'app_id': 'videos',
  'app_namespace_py': 'videos',
  'app_namespace_ts': 'videos',
  'description': 'Get the transcript/content of a specific YouTube video URL.',
  'description_key': 'videos.get_transcript.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of transcript request '
                                                        'objects for parallel processing. \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single transcript.\n'
                                                        'Example for single transcript: '
                                                        '{"requests": [{"url": '
                                                        '"https://youtube.com/watch?v=abc123"}]}\n'
                                                        'Example for multiple transcripts: '
                                                        '{"requests": [{"url": '
                                                        '"https://youtube.com/watch?v=abc123"}, '
                                                        '{"url": '
                                                        '"https://youtube.com/watch?v=def456"}]}\n'
                                                        "Each object must contain 'url' (YouTube "
                                                        'video URL), and can include optional '
                                                        'parameters (languages).\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        "not provided - you don't need to include "
                                                        'it.\n',
                                         'items': {'properties': {'languages': {'default': ['en',
                                                                                            'de',
                                                                                            'es',
                                                                                            'fr'],
                                                                                'description': 'List '
                                                                                               'of '
                                                                                               'language '
                                                                                               'codes '
                                                                                               'to '
                                                                                               'try '
                                                                                               'for '
                                                                                               'transcript '
                                                                                               '(ISO '
                                                                                               '639-1, '
                                                                                               'e.g., '
                                                                                               "'en', "
                                                                                               "'de', "
                                                                                               "'es', "
                                                                                               "'fr'). "
                                                                                               'The '
                                                                                               'API '
                                                                                               'will '
                                                                                               'use '
                                                                                               'the '
                                                                                               'first '
                                                                                               'available '
                                                                                               'language.',
                                                                                'items': {'type': 'string'},
                                                                                'type': 'array'},
                                                                  'url': {'description': 'YouTube '
                                                                                         'video '
                                                                                         'URL '
                                                                                         '(supports '
                                                                                         'youtube.com/watch?v= '
                                                                                         'and '
                                                                                         'youtu.be/ '
                                                                                         'formats)',
                                                                          'type': 'string'}},
                                                   'required': ['url'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'get_transcript',
  'skill_method_py': 'get_transcript',
  'skill_method_ts': 'getTranscript'},
 {'app_id': 'videos',
  'app_namespace_py': 'videos',
  'app_namespace_ts': 'videos',
  'description': 'Search for videos, documentaries, tutorials, clips on the web.',
  'description_key': 'videos.search.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of search request objects '
                                                        'for parallel processing (up to 5 '
                                                        'requests). \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single search.\n'
                                                        'Example for single search: {"requests": '
                                                        '[{"query": "Python tutorial"}]}\n'
                                                        'Example for multiple searches: '
                                                        '{"requests": [{"query": "Python '
                                                        'tutorial"}, {"query": "FastAPI '
                                                        'tutorial"}]}\n'
                                                        "Each object must contain 'query' (search "
                                                        'query string), and can include optional '
                                                        'parameters (count, country, search_lang, '
                                                        'safesearch).\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        "not provided - you don't need to include "
                                                        'it.\n',
                                         'items': {'properties': {'count': {'default': 6,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'results '
                                                                                           'for '
                                                                                           'this '
                                                                                           'request '
                                                                                           '(max '
                                                                                           '20)',
                                                                            'maximum': 20,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'country': {'default': 'us',
                                                                              'description': 'Country '
                                                                                             'code '
                                                                                             'for '
                                                                                             'localized '
                                                                                             'results. '
                                                                                             'Must '
                                                                                             'be '
                                                                                             'one '
                                                                                             'of: '
                                                                                             'AR, '
                                                                                             'AU, '
                                                                                             'AT, '
                                                                                             'BE, '
                                                                                             'BR, '
                                                                                             'CA, '
                                                                                             'CL, '
                                                                                             'DK, '
                                                                                             'FI, '
                                                                                             'FR, '
                                                                                             'DE, '
                                                                                             'GR, '
                                                                                             'HK, '
                                                                                             'IN, '
                                                                                             'ID, '
                                                                                             'IT, '
                                                                                             'JP, '
                                                                                             'KR, '
                                                                                             'MY, '
                                                                                             'MX, '
                                                                                             'NL, '
                                                                                             'NZ, '
                                                                                             'NO, '
                                                                                             'CN, '
                                                                                             'PL, '
                                                                                             'PT, '
                                                                                             'PH, '
                                                                                             'RU, '
                                                                                             'SA, '
                                                                                             'ZA, '
                                                                                             'ES, '
                                                                                             'SE, '
                                                                                             'CH, '
                                                                                             'TW, '
                                                                                             'TR, '
                                                                                             'GB, '
                                                                                             'US, '
                                                                                             'or '
                                                                                             'ALL '
                                                                                             '(case-insensitive). '
                                                                                             'Defaults '
                                                                                             'to '
                                                                                             "'us' "
                                                                                             'if '
                                                                                             'invalid.',
                                                                              'enum': ['AR',
                                                                                       'AU',
                                                                                       'AT',
                                                                                       'BE',
                                                                                       'BR',
                                                                                       'CA',
                                                                                       'CL',
                                                                                       'DK',
                                                                                       'FI',
                                                                                       'FR',
                                                                                       'DE',
                                                                                       'GR',
                                                                                       'HK',
                                                                                       'IN',
                                                                                       'ID',
                                                                                       'IT',
                                                                                       'JP',
                                                                                       'KR',
                                                                                       'MY',
                                                                                       'MX',
                                                                                       'NL',
                                                                                       'NZ',
                                                                                       'NO',
                                                                                       'CN',
                                                                                       'PL',
                                                                                       'PT',
                                                                                       'PH',
                                                                                       'RU',
                                                                                       'SA',
                                                                                       'ZA',
                                                                                       'ES',
                                                                                       'SE',
                                                                                       'CH',
                                                                                       'TW',
                                                                                       'TR',
                                                                                       'GB',
                                                                                       'US',
                                                                                       'ALL',
                                                                                       'ar',
                                                                                       'au',
                                                                                       'at',
                                                                                       'be',
                                                                                       'br',
                                                                                       'ca',
                                                                                       'cl',
                                                                                       'dk',
                                                                                       'fi',
                                                                                       'fr',
                                                                                       'de',
                                                                                       'gr',
                                                                                       'hk',
                                                                                       'in',
                                                                                       'id',
                                                                                       'it',
                                                                                       'jp',
                                                                                       'kr',
                                                                                       'my',
                                                                                       'mx',
                                                                                       'nl',
                                                                                       'nz',
                                                                                       'no',
                                                                                       'cn',
                                                                                       'pl',
                                                                                       'pt',
                                                                                       'ph',
                                                                                       'ru',
                                                                                       'sa',
                                                                                       'za',
                                                                                       'es',
                                                                                       'se',
                                                                                       'ch',
                                                                                       'tw',
                                                                                       'tr',
                                                                                       'gb',
                                                                                       'us',
                                                                                       'all'],
                                                                              'type': 'string'},
                                                                  'query': {'description': 'Search '
                                                                                           'query '
                                                                                           'string',
                                                                            'type': 'string'},
                                                                  'safesearch': {'default': 'moderate',
                                                                                 'description': 'Safe '
                                                                                                'search '
                                                                                                'level',
                                                                                 'enum': ['off',
                                                                                          'moderate',
                                                                                          'strict'],
                                                                                 'type': 'string'},
                                                                  'search_lang': {'default': 'en',
                                                                                  'description': 'Language '
                                                                                                 'code '
                                                                                                 'for '
                                                                                                 'search '
                                                                                                 '(ISO '
                                                                                                 '639-1, '
                                                                                                 'e.g., '
                                                                                                 "'en', "
                                                                                                 "'es', "
                                                                                                 "'fr')",
                                                                                  'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'weather',
  'app_namespace_py': 'weather',
  'app_namespace_ts': 'weather',
  'description': 'Get current and upcoming weather forecasts for a place, including daily weather, '
                 'temperatures, rain likelihood, and hourly details stored in day embeds. Use this '
                 'for weather questions, forecast requests, and trip/day planning involving '
                 'weather.',
  'description_key': 'apps.weather.forecast.description',
  'schema': {'properties': {'days': {'default': 7,
                                     'description': 'Number of forecast days to return. Defaults '
                                                    'to 7. Maximum 14.',
                                     'maximum': 14,
                                     'minimum': 1,
                                     'type': 'integer'},
                            'latitude': {'description': 'Optional latitude in decimal degrees. Use '
                                                        'with longitude for exact coordinates.',
                                         'type': 'number'},
                            'location': {'description': 'Place name for the forecast, e.g. Berlin, '
                                                        'Karlsruhe, Tokyo. Required unless '
                                                        'latitude and longitude are provided.',
                                         'type': 'string'},
                            'longitude': {'description': 'Optional longitude in decimal degrees. '
                                                         'Use with latitude for exact coordinates.',
                                          'type': 'number'},
                            'timezone': {'description': 'Optional IANA timezone. Defaults to '
                                                        'provider/location timezone.',
                                         'type': 'string'},
                            'units': {'default': 'metric',
                                      'description': 'Unit system. Only metric is currently '
                                                     'supported.',
                                      'enum': ['metric'],
                                      'type': 'string'}},
             'required': ['location'],
             'type': 'object'},
  'skill_id': 'forecast',
  'skill_method_py': 'forecast',
  'skill_method_ts': 'forecast'},
 {'app_id': 'weather',
  'app_namespace_py': 'weather',
  'app_namespace_ts': 'weather',
  'description': 'Get nearby German rain radar with a timeline, including whether rain is visible '
                 'now, whether rain is expected around the selected location in about 10 minutes, '
                 'and compact frame-by-frame rain intensity metadata. Use this for rain radar, '
                 'precipitation radar, and hyperlocal "will it rain here soon" questions in '
                 'Germany.',
  'description_key': 'apps.weather.rain_radar.description',
  'schema': {'properties': {'latitude': {'description': 'Optional latitude in decimal degrees. Use '
                                                        'with longitude for exact coordinates. V1 '
                                                        'supports Germany only.',
                                         'type': 'number'},
                            'location': {'description': 'German place name for the radar, e.g. '
                                                        'Berlin, Hamburg, Munich. Required unless '
                                                        'latitude and longitude are provided.',
                                         'type': 'string'},
                            'longitude': {'description': 'Optional longitude in decimal degrees. '
                                                         'Use with latitude for exact coordinates. '
                                                         'V1 supports Germany only.',
                                          'type': 'number'},
                            'radius_km': {'default': 5,
                                          'description': 'Radar radius around the location in '
                                                         'kilometers. Defaults to 5 for a '
                                                         'neighborhood/city-part view. Maximum '
                                                         '100.',
                                          'maximum': 100,
                                          'minimum': 1,
                                          'type': 'integer'},
                            'timezone': {'description': 'Optional IANA timezone. Defaults to '
                                                        'provider/location timezone.',
                                         'type': 'string'}},
             'required': ['location'],
             'type': 'object'},
  'skill_id': 'rain_radar',
  'skill_method_py': 'rain_radar',
  'skill_method_ts': 'rainRadar'},
 {'app_id': 'web',
  'app_namespace_py': 'web',
  'app_namespace_ts': 'web',
  'description': 'General web search for current information, prices, weather, facts, stocks, '
                 'sports scores, etc. Use as a fallback when no specialized skill applies.',
  'description_key': 'app_skills.web.search.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of search request objects '
                                                        'for parallel processing (up to 5 '
                                                        'requests). \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single search.\n'
                                                        'Example for single search: {"requests": '
                                                        '[{"query": "Python async"}]}\n'
                                                        'Example for multiple searches: '
                                                        '{"requests": [{"query": "Python async"}, '
                                                        '{"query": "FastAPI best practices"}]}\n'
                                                        "Each object must contain 'query' (search "
                                                        'query string), and can include optional '
                                                        'parameters (count, country, search_lang, '
                                                        'safesearch).\n'
                                                        "Note: The 'id' field is auto-generated if "
                                                        "not provided - you don't need to include "
                                                        'it.\n',
                                         'items': {'properties': {'count': {'default': 6,
                                                                            'description': 'Number '
                                                                                           'of '
                                                                                           'results '
                                                                                           'for '
                                                                                           'this '
                                                                                           'request '
                                                                                           '(max '
                                                                                           '20)',
                                                                            'maximum': 20,
                                                                            'minimum': 1,
                                                                            'type': 'integer'},
                                                                  'country': {'default': 'us',
                                                                              'description': 'Country '
                                                                                             'code '
                                                                                             'for '
                                                                                             'localized '
                                                                                             'results. '
                                                                                             'Must '
                                                                                             'be '
                                                                                             'one '
                                                                                             'of: '
                                                                                             'AR, '
                                                                                             'AU, '
                                                                                             'AT, '
                                                                                             'BE, '
                                                                                             'BR, '
                                                                                             'CA, '
                                                                                             'CL, '
                                                                                             'DK, '
                                                                                             'FI, '
                                                                                             'FR, '
                                                                                             'DE, '
                                                                                             'GR, '
                                                                                             'HK, '
                                                                                             'IN, '
                                                                                             'ID, '
                                                                                             'IT, '
                                                                                             'JP, '
                                                                                             'KR, '
                                                                                             'MY, '
                                                                                             'MX, '
                                                                                             'NL, '
                                                                                             'NZ, '
                                                                                             'NO, '
                                                                                             'CN, '
                                                                                             'PL, '
                                                                                             'PT, '
                                                                                             'PH, '
                                                                                             'RU, '
                                                                                             'SA, '
                                                                                             'ZA, '
                                                                                             'ES, '
                                                                                             'SE, '
                                                                                             'CH, '
                                                                                             'TW, '
                                                                                             'TR, '
                                                                                             'GB, '
                                                                                             'US, '
                                                                                             'or '
                                                                                             'ALL '
                                                                                             '(case-insensitive). '
                                                                                             'Defaults '
                                                                                             'to '
                                                                                             "'us' "
                                                                                             'if '
                                                                                             'invalid.',
                                                                              'enum': ['AR',
                                                                                       'AU',
                                                                                       'AT',
                                                                                       'BE',
                                                                                       'BR',
                                                                                       'CA',
                                                                                       'CL',
                                                                                       'DK',
                                                                                       'FI',
                                                                                       'FR',
                                                                                       'DE',
                                                                                       'GR',
                                                                                       'HK',
                                                                                       'IN',
                                                                                       'ID',
                                                                                       'IT',
                                                                                       'JP',
                                                                                       'KR',
                                                                                       'MY',
                                                                                       'MX',
                                                                                       'NL',
                                                                                       'NZ',
                                                                                       'NO',
                                                                                       'CN',
                                                                                       'PL',
                                                                                       'PT',
                                                                                       'PH',
                                                                                       'RU',
                                                                                       'SA',
                                                                                       'ZA',
                                                                                       'ES',
                                                                                       'SE',
                                                                                       'CH',
                                                                                       'TW',
                                                                                       'TR',
                                                                                       'GB',
                                                                                       'US',
                                                                                       'ALL',
                                                                                       'ar',
                                                                                       'au',
                                                                                       'at',
                                                                                       'be',
                                                                                       'br',
                                                                                       'ca',
                                                                                       'cl',
                                                                                       'dk',
                                                                                       'fi',
                                                                                       'fr',
                                                                                       'de',
                                                                                       'gr',
                                                                                       'hk',
                                                                                       'in',
                                                                                       'id',
                                                                                       'it',
                                                                                       'jp',
                                                                                       'kr',
                                                                                       'my',
                                                                                       'mx',
                                                                                       'nl',
                                                                                       'nz',
                                                                                       'no',
                                                                                       'cn',
                                                                                       'pl',
                                                                                       'pt',
                                                                                       'ph',
                                                                                       'ru',
                                                                                       'sa',
                                                                                       'za',
                                                                                       'es',
                                                                                       'se',
                                                                                       'ch',
                                                                                       'tw',
                                                                                       'tr',
                                                                                       'gb',
                                                                                       'us',
                                                                                       'all'],
                                                                              'type': 'string'},
                                                                  'filter_tabloids': {'default': True,
                                                                                      'description': 'Filter '
                                                                                                     'out '
                                                                                                     'tabloid/boulevard '
                                                                                                     'media '
                                                                                                     'sources '
                                                                                                     '(e.g., '
                                                                                                     'BILD, '
                                                                                                     'Daily '
                                                                                                     'Mail, '
                                                                                                     'TMZ, '
                                                                                                     'The '
                                                                                                     'Sun) '
                                                                                                     'from '
                                                                                                     'results. '
                                                                                                     'Enabled '
                                                                                                     'by '
                                                                                                     'default '
                                                                                                     'for '
                                                                                                     'quality '
                                                                                                     'results. '
                                                                                                     'Set '
                                                                                                     'to '
                                                                                                     'false '
                                                                                                     'ONLY '
                                                                                                     'if '
                                                                                                     'the '
                                                                                                     'user '
                                                                                                     'explicitly '
                                                                                                     'asks '
                                                                                                     'for '
                                                                                                     'tabloid '
                                                                                                     'sources.',
                                                                                      'type': 'boolean'},
                                                                  'query': {'description': 'Search '
                                                                                           'query '
                                                                                           'string',
                                                                            'type': 'string'},
                                                                  'safesearch': {'default': 'moderate',
                                                                                 'description': 'Safe '
                                                                                                'search '
                                                                                                'level',
                                                                                 'enum': ['off',
                                                                                          'moderate',
                                                                                          'strict'],
                                                                                 'type': 'string'},
                                                                  'search_lang': {'default': 'en',
                                                                                  'description': 'Language '
                                                                                                 'code '
                                                                                                 'for '
                                                                                                 'search '
                                                                                                 '(ISO '
                                                                                                 '639-1, '
                                                                                                 'e.g., '
                                                                                                 "'en', "
                                                                                                 "'es', "
                                                                                                 "'fr')",
                                                                                  'type': 'string'}},
                                                   'required': ['query'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'},
 {'app_id': 'web',
  'app_namespace_py': 'web',
  'app_namespace_ts': 'web',
  'description': 'Read and extract content from a specific URL or webpage the user provided.',
  'description_key': 'web.read.description',
  'schema': {'properties': {'requests': {'description': 'REQUIRED: Array of read request objects '
                                                        'for parallel processing (up to 5 '
                                                        'requests). \n'
                                                        'This parameter is MANDATORY - you MUST '
                                                        "always provide a 'requests' array, even "
                                                        'for a single URL.\n'
                                                        'Example for single URL: {"requests": '
                                                        '[{"id": 1, "url": '
                                                        '"https://example.com/article"}]}\n'
                                                        'Example for multiple URLs: {"requests": '
                                                        '[{"id": 1, "url": '
                                                        '"https://example.com/article1"}, {"id": '
                                                        '2, "url": '
                                                        '"https://example.com/article2"}]}\n'
                                                        "Each object must contain 'id' (unique "
                                                        "identifier) and 'url' (webpage URL), and "
                                                        'can include optional parameters (formats, '
                                                        'only_main_content, max_age, timeout).\n',
                                         'items': {'properties': {'formats': {'default': ['markdown'],
                                                                              'description': 'List '
                                                                                             'of '
                                                                                             'output '
                                                                                             'formats '
                                                                                             'to '
                                                                                             'include '
                                                                                             '(e.g., '
                                                                                             "'markdown', "
                                                                                             "'html', "
                                                                                             "'summary')",
                                                                              'items': {'type': 'string'},
                                                                              'type': 'array'},
                                                                  'max_age': {'description': 'Cache '
                                                                                             'age '
                                                                                             'in '
                                                                                             'milliseconds '
                                                                                             '(default: '
                                                                                             '172800000 '
                                                                                             '= 2 '
                                                                                             'days). '
                                                                                             'Returns '
                                                                                             'cached '
                                                                                             'version '
                                                                                             'if '
                                                                                             'available.',
                                                                              'type': 'integer'},
                                                                  'only_main_content': {'default': True,
                                                                                        'description': 'Whether '
                                                                                                       'to '
                                                                                                       'return '
                                                                                                       'only '
                                                                                                       'main '
                                                                                                       'content '
                                                                                                       '(excluding '
                                                                                                       'headers, '
                                                                                                       'navs, '
                                                                                                       'footers, '
                                                                                                       'etc.)',
                                                                                        'type': 'boolean'},
                                                                  'timeout': {'description': 'Timeout '
                                                                                             'in '
                                                                                             'milliseconds '
                                                                                             'for '
                                                                                             'the '
                                                                                             'request',
                                                                              'type': 'integer'},
                                                                  'url': {'description': 'URL of '
                                                                                         'the '
                                                                                         'webpage '
                                                                                         'to '
                                                                                         'read/scrape',
                                                                          'type': 'string'}},
                                                   'required': ['url'],
                                                   'type': 'object'},
                                         'type': 'array'}},
             'required': ['requests'],
             'type': 'object'},
  'skill_id': 'read',
  'skill_method_py': 'read',
  'skill_method_ts': 'read'},
 {'app_id': 'workflows',
  'app_namespace_py': 'workflows',
  'app_namespace_ts': 'workflows',
  'description': 'Create or modify exactly one workflow from chat. Do not batch multiple workflows '
                 'into one skill call.',
  'description_key': 'workflows.skills.create_or_modify.description',
  'schema': {'properties': {'graph': {'description': 'Valid WorkflowGraph definition.',
                                      'type': 'object'},
                            'title': {'description': 'Short user-facing workflow title.',
                                      'type': 'string'},
                            'workflow_id': {'description': 'Existing workflow ID when modifying a '
                                                           'workflow.',
                                            'type': 'string'}},
             'required': ['title'],
             'type': 'object'},
  'skill_id': 'create-or-modify',
  'skill_method_py': 'create_or_modify',
  'skill_method_ts': 'createOrModify'},
 {'app_id': 'workflows',
  'app_namespace_py': 'workflows',
  'app_namespace_ts': 'workflows',
  'description': "Search the user's existing persisted workflows before proposing a new "
                 'automation. Include temporary workflows only when the user explicitly asks about '
                 'recent chat-created workflows.',
  'description_key': 'workflows.skills.search.description',
  'schema': {'properties': {'include_temporary': {'description': 'Include temporary chat-created '
                                                                 'workflows in the search results.',
                                                  'type': 'boolean'},
                            'query': {'description': 'Workflow title or intent text to search for.',
                                      'type': 'string'}},
             'type': 'object'},
  'skill_id': 'search',
  'skill_method_py': 'search',
  'skill_method_ts': 'search'}]

SkillRunner = Callable[[str, str, dict[str, Any]], dict[str, Any]]

class AiAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def ask(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: ai.ask.description
        Skill: ai/ask
        """
        return self._run_skill("ai", "ask", input_data)

class BooksAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def translate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: books.translate.description
        Skill: books/translate
        """
        return self._run_skill("books", "translate", input_data)

class CodeAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def add_issue(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: code.add_issue.description
        Skill: code/add_issue
        """
        return self._run_skill("code", "add_issue", input_data)

    def clean_repo(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: code.clean_repo.description
        Skill: code/clean_repo
        """
        return self._run_skill("code", "clean_repo", input_data)

    def get_docs(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Get latest documentation for programming libraries, frameworks, APIs, SDKs. Use for ANY programming-related query about a specific library or framework.

        Description key: code.get_docs.description
        Skill: code/get_docs
        """
        return self._run_skill("code", "get_docs", input_data)

    def get_issues(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: code.get_issues.description
        Skill: code/get_issues
        """
        return self._run_skill("code", "get_issues", input_data)

    def get_project_overview(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: code.get_project_overview.description
        Skill: code/get_project_overview
        """
        return self._run_skill("code", "get_project_overview", input_data)

    def remove_secrets(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: code.remove_secrets.description
        Skill: code/remove_secrets
        """
        return self._run_skill("code", "remove_secrets", input_data)

    def search_repos(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search GitHub repositories. Use this instead of web.search whenever the user asks to find GitHub repos, repositories, open-source libraries, starred repos, or repo examples by topic, language, framework, or project need. Returns licensed repository embeds. Costs 10 credits per search.

        Description key: code.search_repos.description
        Skill: code/search_repos
        """
        return self._run_skill("code", "search_repos", input_data)

class DesignAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search_icons(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for free SVG icons for UI, product, interface, or graphic design. Use this when the user asks to find icons by name, concept, object, or action. Do not use it for brand-logo search or generated icon creation.

        Description key: app_skills.design.search_icons.description
        Skill: design/search_icons
        """
        return self._run_skill("design", "search_icons", input_data)

class ElectronicsAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search_components(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Use this skill when the user asks to find electronic components, especially power converters or voltage regulators matching input voltage, output voltage, output current, efficiency, BOM cost, footprint, or topology requirements. Currently supports category power_converters via Texas Instruments WEBENCH Power Designer.

        Description key: electronics.search_components.description
        Skill: electronics/search_components
        """
        return self._run_skill("electronics", "search_components", input_data)

class EventsAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for local or online events, meetups, hackathons, conferences, workshops, networking events, parties, concerts, or any community gathering. Use ONLY this skill for event searches — do NOT additionally call web.search or any other search skill for the same query. Sources: Meetup, Luma, Eventbrite, Google Events, Resident Advisor (electronic music/clubs), Siegessäule (Berlin LGBTQ+ events), Berlin Philharmonic (classical concerts in Berlin), and official event schedules for GPN24, 39C3, 38C3

        Description key: events.search.description
        Skill: events/search
        """
        return self._run_skill("events", "search", input_data)

class FitnessAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search_classes(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search available Urban Sports Club public fitness classes. Use this when the user asks for dated fitness classes, course availability, free spots, on-site classes, online classes, or plan-filtered Urban Sports classes. Omit plan unless the user explicitly asks for Essential, Classic, Premium, or Max.

        Description key: fitness.search_classes.description
        Skill: fitness/search_classes
        """
        return self._run_skill("fitness", "search_classes", input_data)

    def search_locations(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search Urban Sports Club public fitness locations. Use this when the user asks for gyms, studios, pools, or Urban Sports locations near a city, address, or radius. Do not use it for class availability; use fitness.search_classes for dated class searches.

        Description key: fitness.search_locations.description
        Skill: fitness/search_locations
        """
        return self._run_skill("fitness", "search_locations", input_data)

class HealthAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def create_report(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: health.create_report.description
        Skill: health/create_report
        """
        return self._run_skill("health", "create_report", input_data)

    def search_appointments(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search available medical appointments at German doctors/specialists by speciality and city. Covers any medical booking — general practitioners, specialists (e.g. dentist, dermatologist, gynecologist), scans and imaging (e.g. MRT/MRI, CT, Röntgen, Ultraschall), vaccinations, check-ups, blood tests, and other examinations. Note: "Termin" in a medical context means appointment, not event — route here instead of events-search. Sources: Doctolib, Jameda (Germany only).

        Description key: app_skills.health.search_appointments.description
        Skill: health/search_appointments
        """
        return self._run_skill("health", "search_appointments", input_data)

class HomeAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for apartments, houses, and WG rooms in German cities. Searches ImmoScout24, Kleinanzeigen, and WG-Gesucht simultaneously. Returns listings with prices, sizes, rooms, addresses, and direct links. Costs 10 credits per search. Use when user asks about finding housing in Germany.

        Description key: app_skills.home.search.description
        Skill: home/search
        """
        return self._run_skill("home", "search", input_data)

class ImagesAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def generate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Generate high-quality images from text prompts and/or reference images (image-to-image editing). Also use for: mockups, design concepts, visual mockup creation, logo mockups, product mockups, illustration requests, visual design, concept art, posters, banners, thumbnails, or any request that implies creating a visual output. Use output_filetype="svg" for logos, icons, illustrations, and any other vector graphics that need to be scalable or editable. When the user provides uploaded images as refe

        Description key: images.generate.description
        Skill: images/generate
        """
        return self._run_skill("images", "generate", input_data)

    def generate_draft(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Quickly generate a draft/preview image from a text prompt and/or reference images (image-to-image). Also use for: quick mockups, rough design concepts, draft illustrations, sketches, quick visual previews, or any request for a fast/rough image. When the user provides uploaded images as references (embed_refs), pass them via reference_images. Do not use this for scam, spam, fake-document, fake-endorsement, public-figure impersonation, or watermark/detection-evasion requests.

        Description key: images.generate_draft.description
        Skill: images/generate_draft
        """
        return self._run_skill("images", "generate_draft", input_data)

class MailAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: app_skills.mail.search.description
        Skill: mail/search
        """
        return self._run_skill("mail", "search", input_data)

class MapsAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for places, businesses, restaurants, directions, locations.

        Description key: maps.search.description
        Skill: maps/search
        """
        return self._run_skill("maps", "search", input_data)

class MathAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def calculate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """MANDATORY: Use this skill for ALL mathematical calculations without exception. This includes simple arithmetic such as addition, subtraction, multiplication (written as *, x, or ×), division, and parenthesised expressions like (4x22x7)/2 or (100+50)*3/2. Also use for algebra, trigonometry, calculus, unit conversions, symbolic simplification, equation solving, derivatives, and integrals. NEVER attempt to compute a numeric result yourself — always call this skill so results are guaranteed to be ex

        Description key: math.calculate.description
        Skill: math/calculate
        """
        return self._run_skill("math", "calculate", input_data)

class Models3dAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search public 3D model catalogs for existing models. Use this when the user wants to find, browse, compare, or link to existing 3D-printable or downloadable 3D models. Do not use it to generate new models.

        Description key: app_skills.models3d.search.description
        Skill: models3d/search
        """
        return self._run_skill("models3d", "search", input_data)

class MusicAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def generate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Generate music from a text prompt, including full songs, instrumental tracks, background music, loops, jingles, lyric-based songs, and soundtrack cues. Use this when the user asks to create music or background music. Do not use this to imitate the voice, vocals, cadence, or persona of a real public figure, living artist, famous educator, or recognizable person. Use original voices and styles only, and reject scams, spam, or detection evasion.

        Description key: app_skills.music.generate.description
        Skill: music/generate
        """
        return self._run_skill("music", "generate", input_data)

class NewsAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for news articles, current events, headlines, announcements.

        Description key: news.search.description
        Skill: news/search
        """
        return self._run_skill("news", "search", input_data)

class NutritionAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search_recipes(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search Edamam for recipes by natural-language query and nutrition filters. Returns recipe details with ingredients, step-by-step instructions, images, source links, and nutrition metadata. Recipes without instructions are filtered out. Best for: recipe recommendations, meal planning, dietary filtering, and cooking guidance.

        Description key: app_skills.nutrition.search_recipes.description
        Skill: nutrition/search_recipes
        """
        return self._run_skill("nutrition", "search_recipes", input_data)

class OpenmatesAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def get_docs(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Use when the user shares an openmates.org/docs URL, or asks to read a specific OpenMates documentation page. Automatically triggered when an openmates docs URL is detected in the conversation.

        Description key: openmates_app.get_docs.description
        Skill: openmates/get-docs
        """
        return self._run_skill("openmates", "get-docs", input_data)

    def search_docs(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Use when the user asks about OpenMates features, setup, architecture, or documentation. Searches across all OpenMates documentation to find relevant pages.

        Description key: openmates_app.search_docs.description
        Skill: openmates/search-docs
        """
        return self._run_skill("openmates", "search-docs", input_data)

    def share_usecase(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Use when the user has explicitly agreed to anonymously share a summary of their intended use cases with the OpenMates team to help improve the product. NEVER call this without clear user consent.

        Description key: openmates_app.share_usecase.description
        Skill: openmates/share-usecase
        """
        return self._run_skill("openmates", "share-usecase", input_data)

class PdfAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def read(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Load and read the raw text content (markdown) of specific pages from an uploaded PDF document. Use when the user asks what a PDF says, wants you to summarise sections, or requests information that is likely textual (paragraphs, tables, headings). The embed TOON content includes a TOC and per-page token estimates — use them to select the most relevant pages. Limits output to 50 000 tokens; call again for remaining pages if needed. Pass the exact embed_ref (original filename) from the toon block —

        Description key: pdf.read.description
        Skill: pdf/read
        """
        return self._run_skill("pdf", "read", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for specific text, keywords, or phrases across all pages of an uploaded PDF. Returns matching text blocks with surrounding context and page numbers. Use when the user asks to find where something is mentioned in the document, or when a targeted keyword search is faster than reading entire sections. No LLM call required — pure text search over the OCR data. Pass the exact embed_ref (original filename) from the toon block as file_path.

        Description key: pdf.search.description
        Skill: pdf/search
        """
        return self._run_skill("pdf", "search", input_data)

    def view(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """View one or more page screenshots from an uploaded PDF and return them as multimodal image blocks so the main inference model can see the pages directly. Use when the user asks about the visual layout, diagrams, charts, figures, or images on specific pages. Also useful when text OCR may have been imperfect (e.g. complex tables, mathematical notation, handwriting). Up to 5 pages can be viewed per call. Pass the exact embed_ref (original filename) from the toon block as file_path — the server reso

        Description key: pdf.view.skill_description
        Skill: pdf/view
        """
        return self._run_skill("pdf", "view", input_data)

class ReminderAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def cancel_reminder(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Cancel or delete an existing reminder.

        Description key: reminder.cancel_reminder.description
        Skill: reminder/cancel-reminder
        """
        return self._run_skill("reminder", "cancel-reminder", input_data)

    def list_reminders(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Show the user's existing scheduled reminders.

        Description key: reminder.list_reminders.description
        Skill: reminder/list-reminders
        """
        return self._run_skill("reminder", "list-reminders", input_data)

    def set_reminder(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Schedule, create, or set up reminders for the user. Handles one-time and recurring reminders (e.g., "every morning", "daily at 9am", "weekly", "monthly"). Use when user wants to be reminded, notified, or alerted about something at a specific time or on a recurring schedule. Also use for automating tasks like "get news every day" or "summarize updates weekly".

        Description key: reminder.set_reminder.description
        Skill: reminder/set-reminder
        """
        return self._run_skill("reminder", "set-reminder", input_data)

class ShoppingAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def search_products(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search products on REWE, Amazon, or Stoffe.de with real-time prices. Use category to route groceries, marketplace products, fabrics, sewing supplies, and patterns to compatible providers. Invalid provider/category combinations are rejected.

        Description key: app_skills.shopping.search_products.description
        Skill: shopping/search_products
        """
        return self._run_skill("shopping", "search_products", input_data)

class SocialMediaAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def get_posts(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Fetch recent social media posts from one or more specific platform pages or profiles. Supports Reddit subreddits, Bluesky profile feeds, and Mastodon public profiles. Use for profile monitoring, community research, and finding conversations to review manually. Costs 10 credits per request.

        Description key: app_skills.social_media.get_posts.description
        Skill: social_media/get-posts
        """
        return self._run_skill("social_media", "get-posts", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search supported social platforms for recent public posts around a topic. Use this for topic monitoring and broad discovery across pages/profiles, not for monitoring a known profile; use Get posts for profile/page posts. Omit platform to search every supported social platform. Costs 10 credits per request.

        Description key: app_skills.social_media.search.description
        Skill: social_media/search
        """
        return self._run_skill("social_media", "search", input_data)

class TasksAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def create(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create one or more user-visible tasks. Use this for planning, task capture, or breaking a request into trackable work. Default unclear assignees to the user.

        Description key: tasks.skills.create.description
        Skill: tasks/create
        """
        return self._run_skill("tasks", "create", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search the user's encrypted tasks through a connected capable client. Do not use server-visible metadata as a private task-content search fallback.

        Description key: tasks.skills.search.description
        Skill: tasks/search
        """
        return self._run_skill("tasks", "search", input_data)

class TravelAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def get_flight(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Fetch the real GPS flight track and actual departure/landing times for a specific completed/past flight. Use when the user asks to see how a flight actually went, the real flight path on a map, or actual timing and runway info. Requires the IATA flight number (e.g. 'LH2472') and the departure date. Costs 7 credits per lookup.

        Description key: app_skills.travel.get_flight.description
        Skill: travel/get_flight
        """
        return self._run_skill("travel", "get_flight", input_data)

    def search_connections(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for flight or train connections for a particular date with details (airlines/operators, times, stops, durations, prices). Use when user asks about flights, train connections, or travel between cities on a specific date. Set transport_methods to ["airplane"] for flights or ["train"] for trains. If the user names a provider, set providers to one or more of: google_flights, deutsche_bahn, flix. If no provider is specified, all providers for the selected transport method are searched. Add cou

        Description key: app_skills.travel.search_connections.description
        Skill: travel/search_connections
        """
        return self._run_skill("travel", "search_connections", input_data)

    def search_stays(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run this OpenMates app skill.

        Description key: app_skills.travel.search_stays.description
        Skill: travel/search_stays
        """
        return self._run_skill("travel", "search_stays", input_data)

class VideosAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def create(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create deterministic code-backed videos with Remotion. Use this for text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter. The assistant must write an explicit ```remotion:Name.tsx fence; do not use this for photorealistic footage or generic TSX components.

        Description key: app_skills.videos.create.description
        Skill: videos/create
        """
        return self._run_skill("videos", "create", input_data)

    def generate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Generate short photorealistic or generative footage from text prompts using Google Veo. Use this when the user asks for cinematic footage, realistic scenes, camera movement, stylized animation, or non-deterministic video generation. Do not use this for exact text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter; those requests should use videos.create with an explicit ```remotion:Name.tsx fence instead. Do not use this

        Description key: app_skills.videos.generate.description
        Skill: videos/generate
        """
        return self._run_skill("videos", "generate", input_data)

    def get_transcript(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Get the transcript/content of a specific YouTube video URL.

        Description key: videos.get_transcript.description
        Skill: videos/get_transcript
        """
        return self._run_skill("videos", "get_transcript", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search for videos, documentaries, tutorials, clips on the web.

        Description key: videos.search.description
        Skill: videos/search
        """
        return self._run_skill("videos", "search", input_data)

class WeatherAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def forecast(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Get current and upcoming weather forecasts for a place, including daily weather, temperatures, rain likelihood, and hourly details stored in day embeds. Use this for weather questions, forecast requests, and trip/day planning involving weather.

        Description key: apps.weather.forecast.description
        Skill: weather/forecast
        """
        return self._run_skill("weather", "forecast", input_data)

    def rain_radar(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Get nearby German rain radar with a timeline, including whether rain is visible now, whether rain is expected around the selected location in about 10 minutes, and compact frame-by-frame rain intensity metadata. Use this for rain radar, precipitation radar, and hyperlocal "will it rain here soon" questions in Germany.

        Description key: apps.weather.rain_radar.description
        Skill: weather/rain_radar
        """
        return self._run_skill("weather", "rain_radar", input_data)

class WebAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def read(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Read and extract content from a specific URL or webpage the user provided.

        Description key: web.read.description
        Skill: web/read
        """
        return self._run_skill("web", "read", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """General web search for current information, prices, weather, facts, stocks, sports scores, etc. Use as a fallback when no specialized skill applies.

        Description key: app_skills.web.search.description
        Skill: web/search
        """
        return self._run_skill("web", "search", input_data)

class WorkflowsAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self._run_skill = run_skill

    def create_or_modify(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create or modify exactly one workflow from chat. Do not batch multiple workflows into one skill call.

        Description key: workflows.skills.create_or_modify.description
        Skill: workflows/create-or-modify
        """
        return self._run_skill("workflows", "create-or-modify", input_data)

    def search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search the user's existing persisted workflows before proposing a new automation. Include temporary workflows only when the user explicitly asks about recent chat-created workflows.

        Description key: workflows.skills.search.description
        Skill: workflows/search
        """
        return self._run_skill("workflows", "search", input_data)

class GeneratedAppSkills:
    def __init__(self, run_skill: SkillRunner):
        self.ai = AiAppSkills(run_skill)
        self.books = BooksAppSkills(run_skill)
        self.code = CodeAppSkills(run_skill)
        self.design = DesignAppSkills(run_skill)
        self.electronics = ElectronicsAppSkills(run_skill)
        self.events = EventsAppSkills(run_skill)
        self.fitness = FitnessAppSkills(run_skill)
        self.health = HealthAppSkills(run_skill)
        self.home = HomeAppSkills(run_skill)
        self.images = ImagesAppSkills(run_skill)
        self.mail = MailAppSkills(run_skill)
        self.maps = MapsAppSkills(run_skill)
        self.math = MathAppSkills(run_skill)
        self.models3d = Models3dAppSkills(run_skill)
        self.music = MusicAppSkills(run_skill)
        self.news = NewsAppSkills(run_skill)
        self.nutrition = NutritionAppSkills(run_skill)
        self.openmates = OpenmatesAppSkills(run_skill)
        self.pdf = PdfAppSkills(run_skill)
        self.reminder = ReminderAppSkills(run_skill)
        self.shopping = ShoppingAppSkills(run_skill)
        self.social_media = SocialMediaAppSkills(run_skill)
        self.tasks = TasksAppSkills(run_skill)
        self.travel = TravelAppSkills(run_skill)
        self.videos = VideosAppSkills(run_skill)
        self.weather = WeatherAppSkills(run_skill)
        self.web = WebAppSkills(run_skill)
        self.workflows = WorkflowsAppSkills(run_skill)
