from web.src.utilities.Database_Helpers import *

class Teglon:

    def add_options(self, parser=None, usage=None, config=None):
        import optparse
        if parser == None:
            parser = optparse.OptionParser(usage=usage, conflict_handler="resolve")

        parser.add_option('--healpix_map_id', default="-1", type="int",
                          help='''The integer primary key for the map to remove.''')

        return (parser)

    def main(self):
        is_error = False

        if self.options.healpix_map_id < 0:
            is_error = True
            print("HealpixMap_id is required.")

        if is_error:
            return

        # DeleteMap performs a targeted, transactional delete of ONLY this map's
        # rows (docker/db_init/delete_map.sql). raise_on_error surfaces failures.
        delete_map = 'CALL DeleteMap(%s);' % self.options.healpix_map_id
        query_db([delete_map], commit=True, raise_on_error=True)


if __name__ == "__main__":
    useagestring = """python DeleteMap.py [options]
    
python DeleteMap.py --healpix_map_id <database id>
"""

    start = time.time()

    teglon = Teglon()
    parser = teglon.add_options(usage=useagestring)
    options, args = parser.parse_args()
    teglon.options = options

    teglon.main()

    end = time.time()
    duration = (end - start)
    print("\n********* start DEBUG ***********")
    print("Teglon `DeleteMap` execution time: %s" % duration)
    print("********* end DEBUG ***********\n")


