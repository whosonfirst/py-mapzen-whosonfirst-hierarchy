# py-mapzen-whosonfirst-hierarchy

Simple Python wrapper for Who's On First hierarchies. 

## Usage

_This is all wet-paint. We are working out the details by "doing". The interfaces described below should be stable but please approach this with understanding and the expectation that changes might still be necessary._

### Spatial clients

The first thing to know is that this package requires a spatial "client" or more specifically something that subclasses `mapzen.whosonfirst.spatial.base`.

The second thing to know is that because Python doesn't really implement "interfaces" (or maybe it does and I just know or maybe it does in Python 3 and now we're implementing a yak-shaving interface...) not all clients may implement all the same methods. The base class will raise an exception if a given method hasn't been implemented but, as of this writing, there are no checks to ensure that a minimum set of methods are available when a client is instantiated. One thing at a time.

The third thing to know is that there are valid reasons for having multiple different clients. These might include the need to update things locally, infrastructure burden (not setting up PostGIS), delegating all spatial operations to a remote service and so on. This can introduce an element of bad craziness involving data synchronization and completeness (for example a remote PIP server may not include a given placetype). Life is complicated that way.

For complete documentation of all the available spatial clients please consult the [py-mapzen-whosonfirst-spatial]() package. For the rest of this document we'll assume that you're using the PostGIS client, which is instantiated like this:

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

ancs.rebuild_descendants(feature, callback, data_root=data_root)
```

## See also

* https://github.com/whosonfirst/py-mapzen-whosonfirst-spatial/tree/base