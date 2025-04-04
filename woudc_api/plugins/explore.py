# =================================================================
#
# Terms and Conditions of Use
#
# Unless otherwise noted, computer program source code of this
# distribution # is covered under Crown Copyright, Government of
# Canada, and is distributed under the MIT License.
#
# The Canada wordmark and related graphics associated with this
# distribution are protected under trademark law and copyright law.
# No permission is granted to use them outside the parameters of
# the Government of Canada's corporate identity program. For
# more information, see
# http://www.tbs-sct.gc.ca/fip-pcim/index-eng.asp
#
# Copyright title to all 3rd party software distributed with this
# software is held by the respective copyright holders as noted in
# those files. Users are asked to read the 3rd Party Licenses
# referenced with those assets.
#
# Copyright (c) 2020 Government of Canada
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

import os
import logging

from elasticsearch import Elasticsearch
from elastic_transport import TlsError

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


LOGGER = logging.getLogger(__name__)

PROCESS_SETTINGS = {
    'id': 'woudc-data-registry-explore',
    'title': 'WOUDC Data Registry Search Page Helper',
    'description': 'A WOUDC Data Registry Search Index extension that'
                   ' provides items for all the WOUDC data search page'
                   ' dropdowns, all in one request.',
    'keywords': [],
    'links': [],
    'inputs': {
        'dataset': {
            'title': 'Dataset to Filter',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 0,
            'maxOccurs': 1
        },
        'country': {
            'title': 'Country to Filter',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 0,
            'maxOccurs': 1
        },
        'station': {
            'title': 'Station to Filter',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 0,
            'maxOccurs': 1
        }
    },
    'outputs': {
        'woudc-data-registry-explore-response': {
            'title': 'WOUDC Data Registry Search Page Output',
            "schema": {
                "type": "object",
                "contentMediaType": "application/json"
            }
        }
    },
    'example': {
        'inputs': {
            'dataset': 'OzoneSonde_1.0',
            'country': 'CAN',
            'station': '077'
        }
    }
}


class SearchPageProcessor(BaseProcessor):
    """
    WOUDC Data Registry API extension for the search page.

    Produces lists of features that are relevant for populating the
    dropdowns on the WOUDC data search page. Designed to supply all
    dropdowns in one request to reduce how long it takes.

    Supports several filters, one for most selections on the search page.
    """

    def __init__(self, provider_def):
        """
        Initialize object

        :param provider_def: Provider definition?
        :returns: `woudc_api.plugins.explore.SearchPageProcessor`
        """

        BaseProcessor.__init__(self, provider_def, PROCESS_SETTINGS)

        LOGGER.debug('Setting Elasticsearch properties')
        es_url = os.getenv('WOUDC_API_ES_URL',
                           'http://elastic:password@localhost:9200')
        self.verify_certs = os.getenv(
                            'WOUDC_API_VERIFY_CERTS',
                            'True').strip().lower() in ('true', '1', 'yes')

        host = es_url.split('@', 1)[-1]

        self.index_prefix = os.getenv('WOUDC_API_ES_INDEX_PREFIX',
                                      'woudc_data_registry') + '.'
        self.index = self.index_prefix + 'contribution'

        LOGGER.debug(f"Host: {host}")
        LOGGER.debug(f"Index prefix name: {self.index_prefix}")
        LOGGER.debug(f"Index name: {self.index}")

        LOGGER.debug(
            f"Connecting to Elasticsearch (verify_certs={self.verify_certs})"
        )
        try:
            self.es = Elasticsearch(es_url, verify_certs=self.verify_certs)
        except TlsError as err:
            if self.verify_certs:
                msg = (
                    f"SSL certificate verification failed: {err}.\n"
                    "Check your SSL certificates or set "
                    "WOUDC_API_VERIFY_CERTS=False if "
                    "connecting to an internal test server."
                )
            else:
                msg = f"Unexpected TLS error: {err}"

            LOGGER.error(msg)
            raise ProcessorExecuteError(msg)

        if not self.es.ping():
            msg = f"Cannot connect to Elasticsearch: {host}"
            LOGGER.error(msg)
            raise ProcessorExecuteError(msg)

        LOGGER.debug('Checking Elasticsearch version')
        version = float(self.es.info()['version']['number'][:3])
        if version < 8:
            msg = (
                f"Elasticsearch version below 8 not supported ({version})"
            )
            LOGGER.error(msg)
            raise ProcessorExecuteError(msg)

    def execute(self, inputs: dict, **kwargs):
        """
        Responds to an incoming request to this endpoint of the API.

        :param inputs: Body of the incoming request.
        :returns: Body of the response sent for that request.
        """

        dataset = inputs.get('dataset', None)
        country = inputs.get('country', None)
        station = inputs.get('station', None)
        source = inputs.get('source', None)

        peer_records = False
        if dataset and dataset in ['peer_data_records',
                                   'ndacc_total',
                                   'ndacc_uv',
                                   'ndacc_vertical']:
            self.index = self.index_prefix + 'peer_data_record'
            peer_records = True

        filters = {
            'countries': [],
            'stations': [],
            'instruments': []
        }

        if not peer_records:
            if dataset is not None:
                dataset_list = dataset.split(',')
                dataset_filter = {
                    'bool': {
                        'should': [
                            {'term': {'properties.dataset_id.raw': ds}}
                            for ds in dataset_list
                        ]
                    }
                }

                filters['countries'].append(dataset_filter)
                filters['stations'].append(dataset_filter)
                filters['instruments'].append(dataset_filter)

        else:
            if source is None and dataset in ['ndacc_total',
                                              'ndacc_uv',
                                              'ndacc_vertical']:
                source = 'ndacc'
            measurement = None
            if dataset == 'ndacc_total':
                measurement = 'TOTALCOL'
            if dataset == 'ndacc_uv':
                measurement = 'UV'
            if dataset == 'ndacc_vertical':
                measurement = 'OZONE'

            if source is not None:
                source_filter = {'term': {'properties.source.raw': source}}
                filters['stations'].append(source_filter)
                filters['instruments'].append(source_filter)
            if measurement is not None:
                measurement_filter = {
                        'term': {'properties.measurement.raw': measurement}
                }
                filters['stations'].append(measurement_filter)
                filters['instruments'].append(measurement_filter)

        if country is not None:
            country_filter =  \
                {'term': {'properties.country_id.raw': country}}
            filters['stations'].append(country_filter)
            filters['instruments'].append(country_filter)
            filters['countries'].append(country_filter)

        if station is not None:
            station_filter = {'term': {'properties.station_id.raw': station}}
            filters['instruments'].append(station_filter)
            filters['stations'].append(station_filter)

        if peer_records:
            domain_properties = {
                'countries': {
                    'sortby': [
                        'properties.country_id'
                    ],
                    'return': [
                        'properties.country_id'
                    ]
                },
                'stations': {
                    'sortby': [
                        'properties.station_id'
                    ],
                    'return': [
                        'properties.station_name',
                        'properties.station_id',
                        'geometry'
                    ]
                },
                'instruments': {
                    'sortby': [
                        'properties.instrument_type'
                    ],
                    'return': [
                        'properties.instrument_type'
                    ]
                }
            }

        else:
            domain_properties = {
                'countries': {
                    'sortby': [
                        'properties.country_id'
                    ],
                    'return': [
                        'properties.country_name_en',
                        'properties.country_name_fr',
                        'properties.country_id',
                        'geometry'
                    ]
                },
                'stations': {
                    'sortby': [
                        'properties.station_id'
                    ],
                    'return': [
                        'properties.name',
                        'properties.station_id',
                        'geometry'
                    ]
                },
                'instruments': {
                    'sortby': [
                        'properties.instrument_name'
                    ],
                    'return': [
                        'properties.instrument_name'
                    ]
                }
            }

        aggregations = {}

        for domain, properties in domain_properties.items():
            aggregations[domain] = {
                'filter': {
                    'bool': {
                        'must': filters[domain]
                    }
                },
                'aggregations': {
                    'sortby_{}'.format(sort_prop.replace('properties.', '')): {
                        'terms': {
                            'field': '{}.raw'.format(sort_prop),
                            'size': 10000,
                            'order': {'_key': 'asc'}
                        },
                        'aggregations': {
                            'example': {
                                'top_hits': {
                                    '_source': properties['return'],
                                    'size': 1
                                }
                            }
                        }
                    } for sort_prop in properties['sortby']
                }
            }

        query = {
            'size': 0,
            'aggregations': aggregations
        }

        response = self.es.search(index=self.index, body=query)
        response_body = response['aggregations']
        summary = {}
        for domain, groups in response_body.items():
            aggregation_names = [
                key for key in groups if key not in ['meta', 'doc_count']
            ]

            summary[domain] = {
                aggregation_name: [
                    group['example']['hits']['hits'][0]['_source']
                    for group in groups[aggregation_name]['buckets']
                ] for aggregation_name in aggregation_names
            }

        return 'application/json', summary
