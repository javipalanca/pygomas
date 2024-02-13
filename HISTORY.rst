=======
History
=======

0.5.0 (2024-02-13)
------------------

* Upgraded to SPADE 3.3.2
* Upgraded to spade-bdi 0.3.0
* File refactoring
* Constants moved to Enums

0.4.7 (2022-05-09)
------------------

* Added internal action .delete

0.4.6 (2022-04-05)
------------------

* SPADE version upgraded

0.4.5 (2020-05-12)
------------------

* Fixed minor bug when deregistering services.

0.4.4 (2020-04-13)
------------------

* Upgraded spade and spade-bdi versions.
* Fixed shot method with negative values.

0.4.3 (2020-03-11)
------------------

* Fixed BDI initialization.
* Fixed allied uniform color.
* New pack sprites.
* Default asl now generates packs at target_reached for axis troops

0.4.2 (2020-03-09)
------------------

* Pygame render improvements.
* Sprite size modified.
* Help dialog.
* Show/hide info (health bars and names).

0.4.1 (2020-03-06)
------------------

* Hotfix: fixed bug with flag sprite.

0.4.0 (2020-03-06)
------------------

* Improved create_control_points.
* Fixed import bug.
* New pygame render. With new sprites and animations.

0.3.7 (2020-03-05)
------------------

* Added warning when goto tries to go to invalid coordinates.
* Fixed dump and replay options.
* Changed map_arena.

0.3.6 (2020-02-28)
------------------

* Added new maps.

0.3.5 (2020-02-25)
------------------

* Increased agents velocity.
* Fixed render messaging initialization.
* Fixed look ZeroDivisionError bug.
* Improved pygomas render with tiles.
* Improved pygomas render supporting invisible bases.

0.3.4 (2020-02-24)
------------------

* Added add_custom_actions support.
* Improved create_control_points custom action.
* Updated spade_bdi requirement to 0.2.0.
* Fixed maps path in render.

0.3.3 (2020-02-24)
------------------

* Minor bug fix.
* Upgraded reference to github repository.

0.3.2 (2020-02-19)
------------------

* Added friendly fire.
* Added a probability to miss a shot.
* Fixed agent stop when there are pending messages to be sent.
* Fixed max length bug in text render.
* Moved ontology constants to a new file.


0.3.1 (2020-02-17)
------------------

* Fixed adding new actions in inherited classes.
* Improved logger.
* Added verbosity parameter.
* Improved jps and a* algorithms by avoiding being near walls.


0.3.0 (2020-02-10)
------------------

* Migrated msg format to msgpack.
* Black sttyle applied to code.
* Major refactoring of code in renders.

0.2.3 (2019-07-10)
------------------

* Upgrade default ASLs.
* Agent name in JSON file is no longer required.

0.2.2 (2019-07-10)
------------------

* Change all coordinate actions and beliefs to tuple of coordinates.
* Update spade-bdi.

0.2.1 (2019-07-08)
------------------

* Change the .create_control_points from action to function.
* Change all coordinate actions and beliefs to tuple of coordinates.

0.2.0 (2019-07-05)
------------------

* Added game replay support.
* Added action to register generic services.
* Added turn action for the troop agents.
* Added a new map (map_08)
* Minor bug fixes.

0.1.0 (2019-06-13)
------------------

* First release on PyPI.
