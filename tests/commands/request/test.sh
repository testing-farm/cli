#!/bin/sh -eux
testing-farm request | egrep "^📢 One day I will contact Testing Farm$"
