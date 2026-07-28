-- ============================================================================
-- Movie Tracker — SQLite schema (structure only, no data)
-- Create an empty database from this file:
--     sqlite3 movies.db < movie_tracker_schema.sql
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- MOVIE-LEVEL: facts intrinsic to the film (unchanged between watches)
-- ----------------------------------------------------------------------------
CREATE TABLE movies (
    id           INTEGER PRIMARY KEY,
    title        TEXT    NOT NULL,
    release_year INTEGER            -- optional; distinguishes remakes / same-name films
);

CREATE TABLE actors (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE directors (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE movie_actors (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, actor_id)
);

CREATE TABLE movie_directors (
    movie_id    INTEGER NOT NULL REFERENCES movies(id)    ON DELETE CASCADE,
    director_id INTEGER NOT NULL REFERENCES directors(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, director_id)
);

-- ----------------------------------------------------------------------------
-- VIEWING-LEVEL: one row per time you watched a movie.
-- date, location, rating, notes, and friends all belong to the VIEWING,
-- so a rewatch can carry its own date, place, rating, comments, and companions.
-- ----------------------------------------------------------------------------
CREATE TABLE viewings (
    id            INTEGER PRIMARY KEY,
    movie_id      INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    date_seen     TEXT,          -- ISO 8601 'YYYY-MM-DD'
    location_seen TEXT,          -- e.g. theater name, "Rented", "Cable"
    rating        REAL,          -- your rating for THIS viewing
    notes         TEXT           -- your comments for THIS viewing
);

CREATE TABLE friends (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE viewing_friends (
    viewing_id INTEGER NOT NULL REFERENCES viewings(id) ON DELETE CASCADE,
    friend_id  INTEGER NOT NULL REFERENCES friends(id)  ON DELETE CASCADE,
    PRIMARY KEY (viewing_id, friend_id)
);

-- ----------------------------------------------------------------------------
-- INDEXES: keep the actor / director / friend searches fast
-- ----------------------------------------------------------------------------
CREATE INDEX idx_movies_title       ON movies(title);
CREATE INDEX idx_viewings_movie     ON viewings(movie_id);
CREATE INDEX idx_viewings_date      ON viewings(date_seen);
CREATE INDEX idx_movie_actors_actor ON movie_actors(actor_id);
CREATE INDEX idx_movie_dir_director ON movie_directors(director_id);
CREATE INDEX idx_vf_friend          ON viewing_friends(friend_id);
