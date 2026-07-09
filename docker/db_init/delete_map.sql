USE teglon;
DELIMITER $$
CREATE PROCEDURE `DeleteMap`(IN map_id INT)
BEGIN
    -- Targeted, transactional delete of a SINGLE HealpixMap and its child rows.
    -- On any error the whole delete rolls back, so a failure can only ever affect
    -- the target map -- never other maps. (Previously this proc TRUNCATEd all
    -- seven tables and restored them from *_bak snapshots, which could wipe
    -- unrelated maps if anything failed mid-procedure.)
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;
        -- Child tables first (FK-safe order), then the map row itself.
        DELETE FROM StaticTile_HealpixPixel    WHERE HealpixMap_id = map_id;
        DELETE FROM ObservedTile_HealpixPixel  WHERE HealpixMap_id = map_id;
        DELETE FROM HealpixPixel_Galaxy_Weight WHERE HealpixMap_id = map_id;
        DELETE FROM HealpixPixel_Completeness  WHERE HealpixMap_id = map_id;
        DELETE FROM ObservedTile               WHERE HealpixMap_id = map_id;
        DELETE FROM HealpixPixel               WHERE HealpixMap_id = map_id;
        DELETE FROM HealpixMap                 WHERE id = map_id;
    COMMIT;
END$$
DELIMITER ;
