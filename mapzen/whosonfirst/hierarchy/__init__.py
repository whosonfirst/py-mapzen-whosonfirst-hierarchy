import logging
import deepdiff

import mapzen.whosonfirst.utils
import mapzen.whosonfirst.placetypes

class ancestors:

    def __init__(self, **kwargs):

        # as in something that implements mapzen.whosonfirst.spatial.base
        # it might be postgis, it might the WOF PIP server, it might be
        # something else (20170501/thisisaaronland)

        self.spatialdb = kwargs.get("spatialdb", None)

        # see this: there's a bug in mapzen.whosonfirst.placetypes that causes
        # descendents to get bent when called multiple times... which is bent
        # (20161206/thisisaaronland)

        # I am not sure this is still true so someone should check whether this
        # is still true... (20170501/thisisaaronland)

        # pt = mapzen.whosonfirst.placetypes.placetype("neighbourhood")
        # ambiguous = pt.descendents([ "common", "optional", "common_optional" ])
        # ambiguous.insert(0, "neighbourhood")

        ambiguous = [ 'neighbourhood', 'microhood', 'campus', 'address', 'building', 'venue' ]
        self.is_ambiguous = ambiguous
        
        self.to_skip = [ "address", "building" ]

    def rebuild(self, feature, **kwargs):

        props = feature["properties"]
        wofid = props["wof:id"]

        controlled = props.get("wof:controlled", [])

        old_parent = props.get("wof:parent_id", -1)
        old_hier = props.get("wof:hierarchy", {})

        if not "wof:parent_id" in controlled:

            logging.info("append parent and hierarchy for %s" % wofid)
            self.append_parent_and_hierarchy(feature, **kwargs)

        elif "wof:parent_id" in controlled and old_parent == -3:

            logging.info("append hierarchy but not parent (-3) for %s" % wofid)
            self.append_parent_and_hierarchy(feature, **kwargs)

            # this might happen automagically? not sure right now... (20170308/thisisaaronland)
            feature["properties"]["wof:parent_id"] = -3

        elif not "wof:hierarchy" in controlled:

            logging.info("ensure hierarchy for %s" % wofid)
            self.ensure_hierarchy(feature, **kwargs)

        else:

            logging.warning("not allowed to update either wof:parent_id or wof:hierarchy so there nothing to do for %s" % wofid)
            return False

        props = feature["properties"]

        new_parent = props["wof:parent_id"]
        new_hier = props["wof:hierarchy"]

        if old_parent != new_parent:
            logging.warning("parent ID has changed for %s" % wofid)
            return True

        d = deepdiff.DeepDiff(old_hier, new_hier)

        if len(d.keys()) > 0:
            logging.warning("hierarchy has changed for %s" % wofid)
            return True

        logging.info("nothing has changed when rebuilding the hierarchy for %s" % wofid)
        return False

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

        # this is the meat of it - start looping through possible parents and see if there's
        # a match - be sure to append the hierarchies for any match

        for p in parents:

            kwargs['filters']['wof:placetype_id'] = p.id()
            kwargs['as_feature'] = True

            possible = list(self.spatialdb.point_in_polygon(lat, lon, **kwargs))

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

                    possible = list(self.spatialdb.point_in_polygon(lat, lon, **kwargs))
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

        if not append and kwargs.get("ensure_hierarchy", False):
            self.ensure_hierarchy(feature, **kwargs)

        # ensure common placetypes are always present

        if feature['properties']['wof:parent_id'] in (-1, -3):

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

            _pt = mapzen.whosonfirst.placetypes.placetype(p)

            kwargs = {
                'filters': {
                    'wof:placetype_id' :  _pt.id(),
                    'wof:is_superseded': 0,
                    'wof:is_deprecated': 0
                } ,
                'as_feature': True,
            }

            possible = list(self.spatialdb.point_in_polygon(lat, lon, **kwargs))

            if self.append_possible_hierarchies(feature, possible):
                match = True
                break

        return match

    def append_possible_hierarchies(self, feature, possible, **kwargs):

        ensure_hierarchy = kwargs.get("ensure_hierarchy", False)
        set_parentid = kwargs.get("set_parentid", False)

        count = len(possible)

        logging.debug("%s possible hierarchyes for %s" % (count, feature['properties']['wof:id']))

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

                if feature['properties']['wof:placetype'] in self.is_ambiguous:
                    feature['properties']['wof:parent_id'] = -3                    

            return True    
