=======
pygomas
=======


.. image:: https://img.shields.io/pypi/v/pygomas.svg
        :target: https://pypi.python.org/pypi/pygomas

.. image:: https://img.shields.io/travis/javipalanca/pygomas.svg
        :target: https://travis-ci.org/javipalanca/pygomas

.. image:: https://readthedocs.org/projects/pygomas/badge/?version=latest
        :target: https://pygomas.readthedocs.io/en/latest/?badge=latest
        :alt: Documentation Status




A python capture the flag Game Oriented Multiagent System.


* Free software: GNU General Public License v3
* Documentation: https://pygomas.readthedocs.io. (to be done)


Features
--------

* BDI agents to play a capture the flag game.
* Based on the SPADE Multi-Agent System platform (https://spade-mas.readthedocs.io.)
* Support for different game viewers (pygame, Unity, ncurses...)

===========
Quick Start
===========

To run a pygomas game manager::

    $ pygomas manager --num-players 10 --match-time 120

The prepare a JSON file with your agent configuration::

    {
        "host": "127.0.0.1",
        "manager": "cmanager",
        "service": "cservice",
        "axis": [
            {
                "rank": "BDISoldier",
                "name": "soldier_axis1",
                "password": "secret",
                "amount": 5
            }
        ],
        "allied": [
            {
                "rank": "BDISoldier",
                "name": "soldier_allied1",
                "password": "secret",
                "amount": 5
            }
        ]
    }


For more complex configuration files run::

    $ pygomas help run


Then run your agents file::

    $ pygomas run --game game.json


To view the game play in real time run::

    $ pygomas render

To dump the game play to a file to be replayed in the future run::

    $ pygomas dump --log my_log_file.log

To replay a game play run::

    $ pygomas replay --game my_log_file.log

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
