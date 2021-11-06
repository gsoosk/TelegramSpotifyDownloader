heroku create
heroku buildpacks:add --index 1 https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
heroku buildpacks:add heroku/python
heroku config:set $(cat .env)
git push heroku master
heroku ps:scale worker=1
