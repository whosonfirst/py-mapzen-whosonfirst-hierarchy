import os
import logging
import deepdiff
import pprint

import mapzen.whosonfirst.utils
import mapzen.whosonfirst.export
import mapzen.whosonfirst.placetypes

class ancestors:

    def __init__(self, **kwargs):

        # as in something that implements mapzen.whosonfirst.spatial.base
        # it might be postgis, it might the WOF PIP server, it might be
        # something else (20170501/thisisaaronland)

        self.spatial_client = kwargs.get("spatial_client", None)

        # https://github.com/whosonfirst/py-mapzen-whosonfirst-hierarchy/issues/1
        # -3 something might have multiple neighbourhoods
	# -4 sometimes localities might have multiple counties (or at least NYC)

        self.is_ambiguous_three = [ 'microhood', 'campus', 'address', 'building', 'venue', 'intersection' ]
        self.is_ambiguous_four = [ 'locality' ]
        
        self.to_skip = [ "address", "building" ]

    def rebuild_feature(self, feature, **kwargs):

        props = feature["properties"]
        wofid = props["wof:id"]

        logging.debug("REBUILD %s (%s)" % (props["wof:id"], props["wof:name"]))

        controlled = props.get("wof:controlled", [])

        old_parent = props.get("wof:parent_id", -1)
        old_hier = props.get("wof:hierarchy", {})

        if not "wof:parent_id" in controlled:

            logging.info("append parent and hierarchy for %s" % wofid)
            self.append_parent_and_hierarchy(feature, **kwargs)

        elif "wof:parent_id" in controlled and old_parent in (-3, -4):

            logging.info("append hierarchy but not parent (%s) for %s" % (old_parent, wofid))
            self.append_parent_and_hierarchy(feature, **kwargs)

            # this might happen automagically? not sure right now... (20170308/thisisaaronland)
            feature["properties"]["wof:parent_id"] = old_parent

        elif not "wof:hierarchy" in controlled:

            logging.info("ensure hierarchy for %s" % wofid)
            self.ensure_hierarchy(feature, **kwargs)

        else:

            logging.warning("not allowed to update either wof:parent_id or wof:hierarchy so there nothing to do for %s" % wofid)
            return False

        props = feature["properties"]

        new_parent = props.get("wof:parent_id", -1)
        new_hier = props.get("wof:hierarchy", {})

        if old_parent != new_parent:
            logging.info("parent ID has changed for %s" % wofid)
            return True

        d = deepdiff.DeepDiff(old_hier, new_hier)

        if len(d.keys()) > 0:
            logging.info("hierarchy has changed for %s" % wofid)
            logging.debug(d)
            return True

        logging.info("nothing has changed when rebuilding the hierarchy for %s" % wofid)
        return False

    def rebuild_descendants(self, feature, cb, **kwargs):

        data_root = kwargs.get("data_root", None)
        
        placetypes = kwargs.get("placetypes", None)
        exclude = kwargs.get("exclude", [])
        include = kwargs.get("include", [])

        updated = []

        props = feature["properties"]

        if placetypes == None:

            logging.info("lookup descendants for %s" % props['wof:placetype'])

            pt = mapzen.whosonfirst.placetypes.placetype(props['wof:placetype'])
            placetypes = pt.descendants(['common', 'common_optional', 'optional'])

        logging.info(";".join(placetypes))

        # TO DO: use fancy-pants define placetypes by cli args (include, exclude) code to generate to_skip

        to_skip = [
            'constituency',
            'address',
            'building',
        ]

        for p in to_skip:

            if not p in exclude:
                exclude.append(p)

        for p in placetypes:

            if len(include) and not p in include:
                continue

            if p in exclude:
                continue

            logging.info("find intersecting descendants of placetype %s" % p)

            _p = mapzen.whosonfirst.placetypes.placetype(p)
            pid = _p.id()

            pg_kwargs = {
                'filters': {
                    'wof:placetype_id': pid,
                    'wof:is_superseded': 0,
                    'wof:is_deprecated': 0
                },
                'as_feature': True,
                'check_centroid': True,
            }

            if kwargs.get("buffer", None):
                pg_kwargs["buffer"] = kwargs.get("buffer")

            if p == 'venue':
                pg_kwargs['use_centroid'] = True

            intersects = 0

            # TO DO: do these in parallel... translation: my kingdom for Go's
            # sync.WaitGroup in python... (20161206/thisisaaronland)

            props = feature["properties"]
            logging.debug("INTERSECTS %s (%s) where placetype is %s" % (props["wof:id"], props["wof:name"], p))

            for row in self.spatial_client.intersects_paginated(feature, **pg_kwargs):

                intersects += 1
                
                logging.info("process intersection %s (%s)" % (row['properties']['wof:id'], row['properties']['wof:placetype']))

                # load from disk - HOW CAN WE GET RID OF THIS PIECE?

                props = row['properties']
                wofid = props['wof:id']
                repo = props['wof:repo']
                
                _data = os.path.join(data_root, repo)
                _data = os.path.join(_data, "data")
            
                child = mapzen.whosonfirst.utils.load(_data, wofid)

                _kwargs = {
                    'as_feature': True,
                    'filters': {
                        'wof:placetype_id': pid,
                        'wof:is_superseded': 0,
                        'wof:is_deprecated': 0
                    }
                }

                if self.rebuild_feature(child, **_kwargs):

                    if not cb(child):
                        logging.error("post-rebuild callback failed for %s" % wofid)

                        if kwargs.get("strict", False):
                            raise Exception, "post-rebuild callback failed for %s" % wofid

                        continue

                    if not repo in updated:
                        updated.append(repo)
                        
        return updated

    def append_parent_and_hierarchy(self, feature, **kwargs):

        if not kwargs.has_key("filters"):
            kwargs["filters"] = {}

        lat, lon = mapzen.whosonfirst.utils.reverse_geocoordinates(feature)

        logging.debug("reverse geocoordinates for %s: %s, %s" % (feature['properties']['wof:id'], lat, lon))

        # get the list of possible parents for this feature, filtering out
        # some things we know aren't going concerns right now

        props = feature['properties']
        pt = mapzen.whosonfirst.placetypes.placetype(props['wof:placetype'])

        parents = []

        for p in list(pt.parents()):

            if str(p) in self.to_skip:
                logging.debug("skip point in polygon for %s" % str(p))
                continue

            parents.append(p)

        append = False

        logging.debug("possible reverse parents for %s: %s" % (feature['properties']['wof:id'], ";".join(map(str, parents))))

        # this is the meat of it - start looping through possible parents and see if there's
        # a match - be sure to append the hierarchies for any match

        if len(parents) == 0:
            logging.debug("feature placetype (%s) has no parents" % str(pt))

        for p in parents:

            kwargs['filters']['wof:placetype_id'] = p.id()
            kwargs['filters']['wof:is_superseded'] = 0;
            kwargs['filters']['wof:is_deprecated'] = 0;
            kwargs['as_feature'] = True

            possible = list(self.spatial_client.point_in_polygon(lat, lon, **kwargs))

            logging.debug("find parent (%s) for %s, %s : %s" % (p, lat, lon, len(possible)))

            if self.append_possible_hierarchies(feature, possible, set_parentid=True):
                append = True
                break

        # okay - here is a bunch of special-case code to ensure that localities parented by multiple counties
        # don't clone that information too far down the stack, like to say neighbourhoods or boroughs which
        # should only have a single county in their hierarchy.

        if append and props['wof:placetype'] in ("borough", "macrohood", "neighbourhood"):
            
            if len(feature["properties"]["wof:hierarchy"]) > 1:

                counties = []

                for hier in feature["properties"]["wof:hierarchy"]:

                    c = hier.get("county_id", None)

                    if c and not c in counties:
                        counties.append(c)

                if len(counties) > 1:

                    pt = mapzen.whosonfirst.placetypes.placetype("county")

                    kwargs = {
                        'filters': {
                            'wof:placetype_id' :  pt.id(),
                            'wof:is_superseded': 0,
                            'wof:is_deprecated': 0                    
                        } ,
                        'as_feature': True,
                    }

                    possible = list(self.spatial_client.point_in_polygon(lat, lon, **kwargs))
                    new_hier = []

                    if len(possible) > 0:
                    
                        valid = []

                        for f in possible:
                            valid.append(f["properties"]["wof:id"])

                        for hier in feature["properties"]["wof:hierarchy"]:
                    
                            c = hier.get("county_id", None)

                            if c == None or c in valid:
                                new_hier.append(hier)
                                

                        feature["properties"]["wof:hierarchy"] = new_hier

        # see this - we ensure the hierarchy by default

        if not append and kwargs.get("ensure_hierarchy", True):

            props = feature["properties"]
            logging.debug("no append but ensure hierarchy for %s (%s)" % (props["wof:id"], props["wof:name"]))

            self.ensure_hierarchy(feature, **kwargs)

        # ensure common placetypes are always present

        props = feature["properties"]
        parent_id = props.get("wof:parent_id", None)

        if not parent_id:
            raise Exception, "WOF ID %s (%s) is missing a wof:parent_id property" % (props["wof:id"], props["wof:name"])

        if parent_id in (-1, -3, -4):

            # see what's happening? we're making a list of strings
            common = map(str, mapzen.whosonfirst.placetypes.common())

            for h in feature['properties']['wof:hierarchy']:

                for p in common:

                    k = "%s_id" % p

                    if not h.has_key(k):
                        h[k] = -1


    def ensure_hierarchy(self, feature, **kwargs):

        roles = kwargs.get("roles", [ "common", "common_optional", "optional" ] )

        props = feature["properties"]

        if props.get("wof:parent_id", 0) > 0:
            return True

        if len(props.get("wof:hierarchy", [])) > 0:
            return True
            
        lat, lon = mapzen.whosonfirst.utils.reverse_geocoordinates(feature)

        pt = mapzen.whosonfirst.placetypes.placetype(props["wof:placetype"])

        match = False

        # build on the existing to_skip list and append possible parents
        # because if we've gotten here then we're just going to assume
        # that they've all failed and we're looking for something higher
        # up the stack

        to_skip = self.to_skip

        for p in list(pt.parents()):
            
            p = str(p)

            if not p in to_skip:
                to_skip.append(p)

        # go!

        for p in pt.ancestors(roles):

            if str(p) in to_skip:
                continue

            logging.debug("try to ensure hierarchy for %s with placetype %s" % (props["wof:id"], p))

            _pt = mapzen.whosonfirst.placetypes.placetype(p)

            kwargs = {
                'filters': {
                    'wof:placetype_id' :  _pt.id(),
                    'wof:is_superseded': 0,
                    'wof:is_deprecated': 0
                } ,
                'as_feature': True,
            }

            possible = list(self.spatial_client.point_in_polygon(lat, lon, **kwargs))

            logging.debug("ensure hierarchy for %s with placetype %s : %s possible" % (props["wof:id"], p, len(possible)))

            if self.append_possible_hierarchies(feature, possible):
                logging.debug("successfully ensured hierarchy for %s with placetype %s" % (props["wof:id"], p))
                match = True
                break

        return match

    def append_possible_hierarchies(self, feature, possible, **kwargs):

        ensure_hierarchy = kwargs.get("ensure_hierarchy", False)
        set_parentid = kwargs.get("set_parentid", False)

        count = len(possible)

        logging.debug("%s possible hierarchies for %s" % (count, feature['properties']['wof:id']))

        wofid = feature["properties"]["wof:id"]
        wofpt = "%s_id" % feature["properties"]["wof:placetype"]

        if count == 0:

            feature['properties']['wof:hierarchy'] = []

            if set_parentid:
                feature['properties']['wof:parent_id'] = -1

            if ensure_hierarchy:
                logging.debug("no possible - ensure hier")
                self.ensure_hierarchy(feature, as_feature=True)

            return False

        elif count == 1:

            parent = possible[0]
            parent_id = parent['properties']['wof:id']

            parent_hier = parent['properties']['wof:hierarchy']
            hiers = []

            for _h in parent_hier:
                _h[ wofpt ] = wofid
                hiers.append(_h)

            feature['properties']['wof:hierarchy'] = hiers

            if set_parentid:
                feature['properties']['wof:parent_id'] = parent_id

            if parent_id == -1 and ensure_hierarchy:
                logging.debug("no parent - ensure hier")
                self.ensure_hierarchy(feature, as_feature=True)

            return True

        else:

            hiers = []
            
            for f in possible:

                for _h in f['properties']['wof:hierarchy']:
                    _h[ wofpt ] = wofid
                    hiers.append(_h)
                    
            feature['properties']['wof:hierarchy'] = hiers

            if set_parentid:

                feature['properties']['wof:parent_id'] = -1

                if feature['properties']['wof:placetype'] in self.is_ambiguous_three:
                    feature['properties']['wof:parent_id'] = -3

                if feature['properties']['wof:placetype'] in self.is_ambiguous_four:
                    feature['properties']['wof:parent_id'] = -4

            return True

    def rebuild_and_export_feature(self, feature, **kwargs):

        kwargs["rebuild_feature"] = True
        kwargs["rebuild_descendants"] = True
        kwargs["skip_check"] = True

        return self.rebuild_and_export(feature, **kwargs)

    def rebuild_and_export_descendants(self, feature, **kwargs):

        kwargs["rebuild_feature"] = False
        kwargs["rebuild_descendants"] = True

        return self.rebuild_and_export(feature, **kwargs)

    def rebuild_and_export(self, feature, **kwargs):

        # this is a helper method to wrap calling rebuild_feature and
        # rebuild_descendants and to provide a common function (callback)
        # for updating data in all the necessary places.

        data_root = kwargs.get("data_root", None)

        rebuild_feature = kwargs.get("rebuild_feature", True)
        rebuild_descendants = kwargs.get("rebuild_descendants", True)

        # let's say that sometimes for the purpose of debugging you want
        # to export all your changes to disk but not re-index them in a
        # database because it's a lot easier and faster to `git stash` a
        # repo than to wait around for a database to be indexed. the default
        # is do both unless you say otherwise.

        export = kwargs.get("export", True)
        index = kwargs.get("import", True)

        skip_check = kwargs.get("skip_check", False)

        debug = kwargs.get("debug", False)
        
        if not data_root:
            raise Exception, "You forgot to specify a data_root parameter"

        spatial_client = self.spatial_client

        # here's where we actually write things to disk and touch databases

        def callback(feature):

            props = feature["properties"]
            repo = props.get("wof:repo", None)

            if not repo:
                raise Exception, "WOF ID %s (%s) does not have a wof:repo property" % (props["wof:id"], props["wof:name"])

            root = os.path.join(data_root, repo)
            data = os.path.join(root, "data")
            
            if debug:
                logging.info("debugging enabled but normally we would export %s (%s) here", props['wof:id'], props['wof:name'])
                logging.debug(pprint.pformat(feature['properties']))
            elif export == False:
                logging.info("exporting is disabled but normally we would export %s (%s) here", props['wof:id'], props['wof:name'])                
                logging.debug(pprint.pformat(feature['properties']))
            else:
                logging.debug("EXPORT %s (%s)" % (props["wof:id"], props["wof:name"]))
                exporter = mapzen.whosonfirst.export.flatfile(data)
                path = exporter.export_feature(feature)

            # debugging behaviour is handled by the spatial_client thingy

            if index == False:
                logging.info("indexing is disabled but normally we would index %s (%s) here", props['wof:id'], props['wof:name'])
            else:
                logging.debug("REINDEX %s (%s)" % (props['wof:id'], props['wof:name']))
                spatial_client.index_feature(feature, **kwargs)

            return True

        updated = []

        if rebuild_feature:

            # first update the record itself and invoke the callback
            # if there have been changes

            if self.rebuild_feature(feature, **kwargs) or skip_check:

                if callback(feature):
                    props = feature["properties"]
                    repo = props["wof:repo"]
                    updated.append(repo)
                    
        # now plough through through all the descendants of this place
        # note the part where we pass the callback along in the args

        if rebuild_descendants:

            for repo in self.rebuild_descendants(feature, callback, **kwargs):
                
                if not repo in updated:
                    updated.append(repo)

        # all done

        return updated
