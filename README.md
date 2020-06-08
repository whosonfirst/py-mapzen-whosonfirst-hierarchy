# py-mapzen-whosonfirst-hierarchy

Simple Python wrapper for Who's On First hierarchies.

## Installation

```
sudo pip install -r requirements.txt .
```

## Usage

_This is all wet-paint. We are working out the details by "doing". The interfaces described below should be stable but please approach this with understanding and the expectation that changes might still be necessary._

### Spatial clients

The first thing to know is that this package requires a spatial "client" or more specifically something that subclasses `mapzen.whosonfirst.spatial.base`.

The second thing to know is that because Python doesn't really implement "interfaces" (or maybe it does and I just know or maybe it does in Python 3 and now we're implementing a yak-shaving interface...) not all clients may implement all the same methods. The base class will raise an exception if a given method hasn't been implemented but, as of this writing, there are no checks to ensure that a minimum set of methods are available when a client is instantiated. One thing at a time.

The third thing to know is that there are valid reasons for having multiple different clients. These might include the need to update things locally, infrastructure burden (not setting up PostGIS), delegating all spatial operations to a remote service and so on. This can introduce an element of bad craziness involving data synchronization and completeness (for example a remote PIP server may not include a given placetype). Life is complicated that way.

For complete documentation of all the available spatial clients please consult the [py-mapzen-whosonfirst-spatial](https://github.com/whosonfirst/py-mapzen-whosonfirst-spatial) package. For the rest of this document we'll assume that you're using the PostGIS client, which is instantiated like this:

```
import mapzen.whosonfirst.spatial.postgres
pg_client = mapzen.whosonfirst.spatial.postgres.postgis(**kwargs)
```

### Rebuilding the hierarchy (for a WOF record)

To rebuild the hierarchy for a WOF record you would invoke the `rebuild_feature` method passing it a GeoJSON `Feature` thingy, like this:

```
import mapzen.whosonfirst.hierarchy
import mapzen.whosonfirst.utils

feature = mapzen.whosonfirst.utils.load("/usr/local/data/whosonfirst-data/data", 85834637)	# inner mission (SF)

ancs = mapzen.whosonfirst.hierarchy.ancestors(spatial_client=pg_client)
has_changed = ancs.rebuild_feature(feature)
```

The `rebuild_feature` method will update the in-memory data structure but what happens after that (like persisting it to disk) is up to you.

### Rebuilding (the hierarchy for all) descendants (of a WOF record)

To rebuild all the descendants for a WOF record you would call the `rebuild_descendants` method passing it both a GeoJSON `Feature` thingy and a callback to invoke for each updated record. For example, to write changes (to descendants) to disk you might do something like this:

```
import mapzen.whosonfirst.export
import mapzen.whosonfirst.hierarchy
import mapzen.whosonfirst.utils
import logging

feature = mapzen.whosonfirst.utils.load("/usr/local/data/whosonfirst-data/data", 85834637)	# inner mission (SF)
ancs = mapzen.whosonfirst.hierarchy.ancestors(spatial_client=pg_client)

data_root = "/usr/local/data"

def callback (feature):

    props = feature["properties"]
    repo = props["wof:repo"]

    root = os.path.join(data_root, repo)
    data = os.path.join(root, "data")

    exporter = mapzen.whosonfirst.export.flatfile(data)
    path = exporter.export_feature(feature)

    logging.info("update %s (%s)" % (props['wof:name'], path))
    return True

updated_repos = ancs.rebuild_descendants(feature, callback, data_root=data_root)
```

The `rebuild_descendants` method will return a list of all the unique WOF repos which have records that have been changed.

### Rebuilding and exporting (and indexing) the hierarchy for a WOF record (and all its descendants)

To rebuild all the things - as in a given WOF record and all its descendants - and then both export the changes to disk and reindex those changes (with the spatial client) you would call the `rebuild_descendants_and_export_feature` method passing it both a GeoJSON `Feature` thingy and a callback. This is just a helper method that wraps calls to `rebuild_feature` and `rebuild_descendants` and defines an internal callback to export all changes (to disk or a database or whatever).

```
feature = mapzen.whosonfirst.utils.load("/usr/local/data/whosonfirst-data/data", 85834637)	# inner mission (SF)

data_root = "/usr/local/data"

ancs = mapzen.whosonfirst.hierarchy.ancestors(spatial_client=pg_client)
updated_repos = ancs.rebuild_and_export_feature(feature, data_root=data_root)
```

The `rebuild_descendants_and_export_feature` method will return a list of all the unique WOF repos which have records that have been changed.

It seems like it would be nice to be able to define your own callback, but today you can not.

## Tools

### wof-hierarchy-rebuild

Rebuild the hierarchy for a WOF record. Currently this does _not_ write changes back to disk. It will (as an option). Today it does not.

```
./wof-hierarchy-rebuild -h
Usage: wof-hierarchy-rebuild [options] /path/to/wof/record.geojson

Options:
  -h, --help            show this help message and exit
  -C CLIENT, --client=CLIENT
                        A valid mapzen.whosonfirst.spatial spatial client.
                        (default is 'postgis')
  -U, --update          ... (default is False)
  -D DATA_ROOT, --data_root=DATA_ROOT
                        ... (default is '/usr/local/data')
  --pgis-host=PGIS_HOST
                        ...(default is 'localhost')
  --pgis-username=PGIS_USERNAME
                        ... (default is 'whosonfirst')
  --pgis-password=PGIS_PASSWORD
                        ... (default is None)
  --pgis-database=PGIS_DATABASE
                        ... (default is 'whosonfirst')
  -H, --show-hierarchy  ... (default is False)
  -v, --verbose         Be chatty (default is false)
```

For example:

```
./wof-hierarchy-rebuild -v /usr/local/data/whosonfirst-data-venue-us-ca/data/907/212/647/907212647.geojson
INFO:root:append parent and hierarchy for 907212647
DEBUG:root:reverse geocoordinates for 907212647: 37.764943, -122.419496
DEBUG:root:skip point in polygon for building
DEBUG:root:skip point in polygon for address
DEBUG:root:SELECT id, parent_id, placetype_id, meta, ST_AsGeoJSON(geom), ST_AsGeoJSON(centroid) FROM whosonfirst WHERE ST_Intersects(geom, ST_GeomFromGeoJSON(%s)) AND is_superseded=%s AND is_deprecated=%s AND placetype_id=%s
DEBUG:root:find parent (intersection) for 37.764943, -122.419496 : 0
DEBUG:root:0 possible hierarchyes for 907212647
DEBUG:root:SELECT id, parent_id, placetype_id, meta, ST_AsGeoJSON(geom), ST_AsGeoJSON(centroid) FROM whosonfirst WHERE ST_Intersects(geom, ST_GeomFromGeoJSON(%s)) AND is_superseded=%s AND is_deprecated=%s AND placetype_id=%s
DEBUG:root:find parent (campus) for 37.764943, -122.419496 : 0
DEBUG:root:0 possible hierarchyes for 907212647
DEBUG:root:SELECT id, parent_id, placetype_id, meta, ST_AsGeoJSON(geom), ST_AsGeoJSON(centroid) FROM whosonfirst WHERE ST_Intersects(geom, ST_GeomFromGeoJSON(%s)) AND is_superseded=%s AND is_deprecated=%s AND placetype_id=%s
DEBUG:root:find parent (microhood) for 37.764943, -122.419496 : 0
DEBUG:root:0 possible hierarchyes for 907212647
DEBUG:root:SELECT id, parent_id, placetype_id, meta, ST_AsGeoJSON(geom), ST_AsGeoJSON(centroid) FROM whosonfirst WHERE ST_Intersects(geom, ST_GeomFromGeoJSON(%s)) AND is_superseded=%s AND is_deprecated=%s AND placetype_id=%s
DEBUG:root:find parent (neighbourhood) for 37.764943, -122.419496 : 1
DEBUG:root:1 possible hierarchyes for 907212647
INFO:root:nothing has changed when rebuilding the hierarchy for 907212647
INFO:root:Stamen Design (907212647) has parent ID 85834637 - changed: False
DEBUG:root:[{u'continent_id': 102191575,
  u'country_id': 85633793,
  u'county_id': 102087579,
  u'locality_id': 85922583,
  u'macrohood_id': 1108830809,
  u'neighbourhood_id': 85834637,
  u'region_id': 85688637,
  u'venue_id': 907212647}]
```

## See also

* https://github.com/whosonfirst/py-mapzen-whosonfirst-spatial/
