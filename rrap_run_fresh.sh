#!/bin/bash
rm -rfd ./experiment_data/test1
python -W ignore ./code/main.py --data_folder_name 'test' --max_iter 1 --step_num 1 --patch_config "r" --loss_print_freq 1