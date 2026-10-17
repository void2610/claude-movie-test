import os

# テストの書き出し・レビューを、作品の版として fixtures の下に記録しない
os.environ["MOTION_NO_TRAIL"] = "1"
