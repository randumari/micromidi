yes '0' | head -n $(wc -l < $1) > tmp_column.txt
sed -i '1c\Pitch_Bend' tmp_column.txt
paste -d',' <(cut -d',' -f1 $1) tmp_column.txt <(cut -d',' -f2- $1)
rm tmp_column.txt
